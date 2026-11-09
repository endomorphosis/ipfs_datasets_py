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

_NORMATIVE_EXPECTED_VOCABULARY = [
    "<pad>", "<bos>", "<eos>", '"F"', '"O"', '"P"', '"action"',
    '"actor"', '"approve"', '"archive"', '"conditions"', '"deliver"',
    '"examine"', '"exceptions"', '"modality"', '"notary"', '"notice"',
    '"object"', '"preserve"', '"publish"', '"registrar"', '"rules"',
    '"secretary"', '"temporal"', '"treasurer"', '"trustee"', ",", ":",
    "[", "]", "{", "}",
]


def _normative_request(*, dimension=384, recipe="normative-wording-ce",
                       contract="normative-selected-cached-legal-ir/v1", rows=None):
    if rows is None:
        rows = [{"id": "occurrence-a", "source_sha256": "a" * 64,
                 "canonical_ir": legal_target(actor="notary", action="approve", obj="notice")}]
    return {
        "schema": "normative-legal-ir-target-inspection-request/v1",
        "decoder_request": {
            "ir_family_id": "legal_ir", "dimension": dimension,
            "dimension_role": "input_embedding", "task_id": "semantic_IR_reconstruction",
            "checkpoint_sha256": "b" * 64, "decoder_contract_id": contract,
            "training_recipe_name": recipe,
        },
        "rows": deepcopy(rows),
    }


def _normative_inspect(request, *, expected=None):
    raw = canonical(request).encode("utf-8")
    return compatibility.inspect_normative_legal_ir_targets(
        raw, expected_request_sha256=hashlib.sha256(raw).hexdigest() if expected is None else expected)


def _normative_assert_unqualified(report):
    assert report["authority"] and all(flag is False for flag in report["authority"].values())
    for flag in ("model_load_performed", "inference_executed", "targets_forwarded_to_model",
                 "file_io_performed", "network_executed", "source_payloads_replayed"):
        assert report[flag] is False
    for row in report["rows"]:
        assert row["native_grammar_verified"] is False
        assert row["source_binding_verified"] is False
        assert row["reviewed_target"] is False
        assert "canonical_ir" not in row and "source_text" not in row


@pytest.mark.parametrize("dimension", [384, 768])
@pytest.mark.parametrize("recipe", ["normative-wording-zero", "normative-wording-ce"])
@pytest.mark.parametrize("contract", [
    "normative-selected-cached-legal-ir/v1",
    "normative-retained-source-cache-legal-ir/v1",
    "arbitrary-native-source-cache-legal-ir/v1",
])
def test_normative_exact_declared_profiles_keep_fixed_codec_without_asset_claims(dimension, recipe, contract):
    request = _normative_request(dimension=dimension, recipe=recipe, contract=contract)
    raw = canonical(request).encode("utf-8")
    report = _normative_inspect(request)
    expected_codec = {"schema": "typed-json-lexical/v1",
                      "target_vocabulary": _NORMATIVE_EXPECTED_VOCABULARY}
    assert report["schema"] == "normative-legal-ir-target-inspection/v1"
    assert report["request_sha256"] == hashlib.sha256(raw).hexdigest()
    assert report["decoder_request"] == request["decoder_request"]
    assert report["codec_profile"]["schema"] == expected_codec["schema"]
    assert report["codec_profile"]["vocabulary_size"] == 32
    assert report["codec_profile"]["codec_sha256"] == hashlib.sha256(
        canonical(expected_codec).encode("utf-8")).hexdigest()
    assert report["codec_profile"]["max_target_tokens"] == 512
    assert report["codec_profile"]["vocabulary_changed"] is False
    assert report["rows"][0]["status"] == "covered"
    assert report["counts"]["selected"] == report["counts"]["covered"] == 1
    _normative_assert_unqualified(report)


def test_normative_known_word_role_swap_is_lexical_coverage_without_meaning():
    # These whole quoted words are in the codec, but belong to different TRAIN roles.
    target = legal_target(actor="approve", action="notary", obj="notice")
    request = _normative_request(rows=[{"id": "swapped-roles", "source_sha256": "a" * 64,
                                         "canonical_ir": target}])
    row = _normative_inspect(request)["rows"][0]
    assert row["status"] == "covered" and row["lexical_encoding_covered"] is True
    assert row["target_shape_supported"] is True and row["missing_tokens"] == []
    assert row["reviewed_target"] is False and row["native_grammar_verified"] is False


@pytest.mark.parametrize("damage", ["joint_swap", "joint_duplicate"])
def test_normative_matching_changed_codec_owners_cannot_redefine_the_fixed_contract(monkeypatch, damage):
    changed = list(_NORMATIVE_EXPECTED_VOCABULARY)
    if damage == "joint_swap":
        changed[3], changed[4] = changed[4], changed[3]
    else:
        changed[4] = changed[3]
    with monkeypatch.context() as guard:
        guard.setattr(compatibility.normative, "_VOCABULARY", list(changed))
        guard.setattr(compatibility.authored, "VOCABULARY", list(changed))
        with pytest.raises(compatibility.TargetCompatibilityError):
            _normative_inspect(_normative_request())
    assert _normative_inspect(_normative_request())["rows"][0]["status"] == "covered"


@pytest.mark.parametrize("atom", ["approve notice", "notary officer", 'notary "notice"'])
def test_normative_oov_quoted_atom_is_not_replaced_by_known_substrings(atom):
    target = legal_target(actor=atom, action="approve", obj="notice")
    request = _normative_request(rows=[{"id": "whole-atom", "source_sha256": "a" * 64,
                                         "canonical_ir": target}])
    row = _normative_inspect(request)["rows"][0]
    assert row["status"] == "incompatible" and row["target_shape_supported"] is True
    assert row["lexical_encoding_covered"] is False and row["over_limit"] is False
    assert [item["token"] for item in row["missing_tokens"]] == [canonical(atom)]
    assert row["token_count_including_bos_eos"] == 40


def test_normative_complete_512_and_513_id_targets_keep_independent_shape_and_budget():
    # Independent counts: outer punctuation/key = 6 tokens; each quoted atom = 1.
    # 251 atoms + [] + 251 separators + 6 outer tokens + BOS/EOS = 512.
    # 253 atoms + 252 separators + 6 outer tokens + BOS/EOS = 513.
    targets = [{"rules": ["archive"] * 251 + [[]]}, {"rules": ["archive"] * 253}]
    request = _normative_request(rows=[
        {"id": "exact-cap", "source_sha256": "a" * 64, "canonical_ir": targets[0]},
        {"id": "over-cap", "source_sha256": "a" * 64, "canonical_ir": targets[1]},
    ])
    report = _normative_inspect(request)
    assert [row["status"] for row in report["rows"]] == ["unsupported", "unsupported"]
    assert [row["target_shape_supported"] for row in report["rows"]] == [False, False]
    assert [row["token_count_including_bos_eos"] for row in report["rows"]] == [512, 513]
    assert [row["over_limit"] for row in report["rows"]] == [False, True]
    assert [row["lexical_encoding_covered"] for row in report["rows"]] == [True, False]
    assert all(row["missing_tokens"] == [] for row in report["rows"])
    assert report["counts"]["selected"] == report["counts"]["unsupported"] == 2
    assert report["counts"]["over_limit"] == 1


def test_normative_mixed_population_preserves_pending_unsupported_and_oov_rows():
    known = legal_target(actor="notary", action="approve", obj="notice")
    oov = legal_target(actor="officer", action="approve", obj="notice")
    targets = [known, oov, None, {"forall": "notary"}]
    request = _normative_request(rows=[
        {"id": name, "source_sha256": "a" * 64, "canonical_ir": target}
        for name, target in zip(["known", "unknown-atom", "pending", "unsupported"], targets)
    ])
    report = _normative_inspect(request)
    assert [row["id"] for row in report["rows"]] == [row["id"] for row in request["rows"]]
    assert [row["status"] for row in report["rows"]] == ["covered", "incompatible", "pending", "unsupported"]
    assert report["counts"] == {"selected": 4, "covered": 1, "incompatible": 1,
        "unsupported": 1, "pending": 1, "with_oov": 2, "over_limit": 0}
    pending = report["rows"][2]
    assert pending["target_sha256"] is None and pending["lexical_encoding_covered"] is None
    assert pending["target_shape_supported"] is None and pending["token_count_including_bos_eos"] is None
    assert pending["over_limit"] is None and pending["missing_tokens"] == []
    _normative_assert_unqualified(report)


def test_normative_same_source_hash_keeps_distinct_occurrence_ids_and_alternatives():
    target = legal_target(actor="notary", action="approve", obj="notice")
    alternative = deepcopy(target)
    alternative["rules"][0]["modality"] = "P"
    request = _normative_request(rows=[
        {"id": "same-source-alternative-b", "source_sha256": "a" * 64, "canonical_ir": alternative},
        {"id": "same-source-alternative-a", "source_sha256": "a" * 64, "canonical_ir": target},
    ])
    report = _normative_inspect(request)
    assert report["counts"]["selected"] == 2
    assert [row["id"] for row in report["rows"]] == [row["id"] for row in request["rows"]]
    assert report["rows"][0]["source_sha256"] == report["rows"][1]["source_sha256"]
    assert report["rows"][0]["target_sha256"] != report["rows"][1]["target_sha256"]


def test_normative_duplicate_row_id_refuses_instead_of_collapsing_population():
    request = _normative_request()
    request["rows"].append(deepcopy(request["rows"][0]))
    with pytest.raises(compatibility.TargetCompatibilityError):
        _normative_inspect(request)


def test_normative_qualifier_order_and_duplicates_are_preserved_without_native_claim():
    target = legal_target(actor="notary", action="approve", obj="notice",
                          conditions=["notice", "archive", "notice"])
    request = _normative_request(rows=[{"id": "ordered-qualifiers", "source_sha256": "a" * 64,
                                         "canonical_ir": target}])
    row = _normative_inspect(request)["rows"][0]
    assert row["status"] == "covered" and row["target_shape_supported"] is True
    assert row["target_sha256"] == hashlib.sha256(canonical(target).encode("utf-8")).hexdigest()
    sequence = ["<bos>", *lexical_tokens(target), "<eos>"]
    assert row["canonical_token_sequence_sha256"] == hashlib.sha256(canonical(sequence).encode()).hexdigest()
    assert row["native_grammar_verified"] is False


def test_normative_eight_and_nine_rule_declarations_do_not_relabel_lexical_coverage():
    rule = legal_target(actor="notary", action="approve", obj="notice")["rules"][0]
    request = _normative_request(rows=[
        {"id": "eight", "source_sha256": "a" * 64, "canonical_ir": {"rules": [rule] * 8}},
        {"id": "nine", "source_sha256": "a" * 64, "canonical_ir": {"rules": [rule] * 9}},
    ])
    rows = _normative_inspect(request)["rows"]
    assert [row["token_count_including_bos_eos"] for row in rows] == [271, 304]
    assert [row["target_shape_supported"] for row in rows] == [True, False]
    assert [row["lexical_encoding_covered"] for row in rows] == [True, True]
    assert [row["status"] for row in rows] == ["covered", "unsupported"]
    assert all(row["native_grammar_verified"] is False for row in rows)


@pytest.mark.parametrize("damage", [
    "duplicate_outer", "duplicate_target", "nan", "infinity", "utf8", "root_list", "float_overflow",
])
def test_normative_strict_json_does_not_silently_change_supplied_targets(damage):
    raw = canonical(_normative_request()).encode("utf-8")
    if damage == "duplicate_outer":
        raw = b'{"schema":"ignored",' + raw[1:]
    elif damage == "duplicate_target":
        raw = raw.replace(b'"canonical_ir":{', b'"canonical_ir":{"rules":[],', 1)
    elif damage == "nan":
        raw = raw.replace(b'"canonical_ir":{', b'"canonical_ir":{"extra":NaN,', 1)
    elif damage == "infinity":
        raw = raw.replace(b'"canonical_ir":{', b'"canonical_ir":{"extra":Infinity,', 1)
    elif damage == "utf8":
        raw = b"\xff"
    elif damage == "float_overflow":
        raw = raw.replace(b'"canonical_ir":{', b'"canonical_ir":{"extra":1e999,', 1)
    else:
        raw = b"[]"
    with pytest.raises(compatibility.TargetCompatibilityError):
        compatibility.inspect_normative_legal_ir_targets(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("damage", [
    "outer_extra", "outer_missing", "decoder_extra", "dimension_bool", "dimension_float",
    "dimension_8", "dimension_4096", "wrong_task", "source_hash_type", "target_list",
    "wrong_family", "wrong_role", "bad_checkpoint_sha", "wrong_recipe", "unknown_contract",
    "rows_empty", "row_extra", "target_surrogate",
])
def test_normative_closed_types_and_dimensions_cannot_fall_back_to_a_declared_profile(damage):
    request = _normative_request()
    if damage == "outer_extra": request["reviewed"] = True
    elif damage == "outer_missing": del request["rows"]
    elif damage == "decoder_extra": request["decoder_request"]["target_ids"] = [1, 2]
    elif damage == "dimension_bool": request["decoder_request"]["dimension"] = True
    elif damage == "dimension_float": request["decoder_request"]["dimension"] = 384.0
    elif damage == "dimension_8": request["decoder_request"]["dimension"] = 8
    elif damage == "dimension_4096": request["decoder_request"]["dimension"] = 4096
    elif damage == "wrong_task": request["decoder_request"]["task_id"] = "typed_relational_IR_reconstruction"
    elif damage == "source_hash_type": request["rows"][0]["source_sha256"] = None
    elif damage == "target_list": request["rows"][0]["canonical_ir"] = []
    elif damage == "wrong_family": request["decoder_request"]["ir_family_id"] = "intent_ir"
    elif damage == "wrong_role": request["decoder_request"]["dimension_role"] = "latent"
    elif damage == "bad_checkpoint_sha": request["decoder_request"]["checkpoint_sha256"] = "G" * 64
    elif damage == "wrong_recipe": request["decoder_request"]["training_recipe_name"] = "normative-wording-new"
    elif damage == "unknown_contract": request["decoder_request"]["decoder_contract_id"] = "normative-future/v1"
    elif damage == "rows_empty": request["rows"] = []
    elif damage == "row_extra": request["rows"][0]["reviewed"] = True
    else: request["rows"][0]["canonical_ir"] = {"rules": ["\ud800"]}
    with pytest.raises(compatibility.TargetCompatibilityError):
        _normative_inspect(request)


@pytest.mark.parametrize("damage", ["request_bytes", "row_count", "target_bytes", "depth", "nodes"])
def test_normative_complete_input_bounds_refuse_without_selecting_a_subset(damage):
    request = _normative_request()
    if damage == "row_count":
        request["rows"] = [{"id": "pending-%02d" % i, "source_sha256": "a" * 64,
                            "canonical_ir": None} for i in range(65)]
    elif damage == "target_bytes":
        request["rows"][0]["canonical_ir"] = {"rules": ["a" * (512 * 1024)]}
    elif damage == "depth":
        target = {}
        for _ in range(65):
            target = {"rules": target}
        request["rows"][0]["canonical_ir"] = target
    elif damage == "nodes":
        request["rows"][0]["canonical_ir"] = {"rules": [[]] * 100001}
    raw = canonical(request).encode("utf-8")
    if damage == "request_bytes":
        raw += b" " * (2 * 1024 * 1024 + 1 - len(raw))
    with pytest.raises(compatibility.TargetCompatibilityError):
        compatibility.inspect_normative_legal_ir_targets(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest())


def test_normative_independent_raw_request_pin_refuses_a_changed_transport():
    raw = canonical(_normative_request()).encode("utf-8")
    expected = hashlib.sha256(raw).hexdigest()
    with pytest.raises(compatibility.TargetCompatibilityError):
        compatibility.inspect_normative_legal_ir_targets(raw + b" ", expected_request_sha256=expected)


def test_normative_declared_hash_changes_do_not_authenticate_checkpoint_or_source_bytes():
    request = _normative_request()
    first = _normative_inspect(request)
    request["decoder_request"]["checkpoint_sha256"] = "c" * 64
    request["rows"][0]["source_sha256"] = "d" * 64
    second = _normative_inspect(request)
    assert second["decoder_request"]["checkpoint_sha256"] == "c" * 64
    assert second["rows"][0]["source_sha256"] == "d" * 64
    assert second["request_sha256"] != first["request_sha256"]
    assert second["counts"] == first["counts"]
    for flag in ("checkpoint_binding_verified", "source_binding_verified", "preprocessing_binding_verified",
                 "runtime_bindings_verified", "reviewed_targets_established"):
        assert second["authority"][flag] is False
    _normative_assert_unqualified(second)


def test_normative_inspection_preserves_caller_inputs_and_returns_detached_results():
    request = _normative_request()
    before = deepcopy(request)
    first = _normative_inspect(request)
    assert request == before
    first["decoder_request"]["dimension"] = 8
    first["rows"][0]["missing_tokens"].append({"position": 0, "token": "injected"})
    first["authority"]["source_binding_verified"] = True
    second = _normative_inspect(request)
    assert request == before and second["decoder_request"]["dimension"] == 384
    assert second["rows"][0]["missing_tokens"] == []
    _normative_assert_unqualified(second)


def test_normative_inspection_performs_no_file_model_network_or_process_operation(monkeypatch):
    import builtins
    import os
    import socket
    import subprocess
    from ipfs_datasets_py.logic.formalization.autoencoder import normative_legal_ir_runtime as normative_owner

    request = _normative_request()
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("metadata-only inspection attempted an external operation")
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "numpy", "transformers", "requests", "httpx", "duckdb", "pyarrow"}:
            return forbidden(name)
        return original_import(name, *args, **kwargs)
    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(builtins, "__import__", guarded_import)
        guard.setattr(os, "open", forbidden)
        guard.setattr(Path, "open", forbidden)
        guard.setattr(socket, "socket", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(normative_owner, "prepare_normative_legal_ir_runtime", forbidden)
        guard.setattr(normative_owner, "open_normative_legal_ir_autoencoder", forbidden)
        guard.setattr(compatibility.routing, "_read_pin", forbidden)
        report = _normative_inspect(request)
    assert calls == []
    _normative_assert_unqualified(report)


def test_normative_hub_delegate_matches_direct_inspection_without_adding_runtime_inputs():
    request = _normative_request()
    raw = canonical(request).encode("utf-8")
    expected = hashlib.sha256(raw).hexdigest()
    direct = compatibility.inspect_normative_legal_ir_targets(raw, expected_request_sha256=expected)
    delegated = hub.inspect_normative_legal_ir_targets(raw, expected_request_sha256=expected)
    assert delegated == direct
    delegated["rows"].clear()
    assert direct["rows"]
    _normative_assert_unqualified(direct)


from ipfs_datasets_py.logic.formalization.autoencoder import arbitrary_native_legal_ir_runtime as bound_arbitrary
from ipfs_datasets_py.logic.formalization.autoencoder import arbitrary_native_source_cache as bound_cache
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_runtime as bound_contextual
from ipfs_datasets_py.logic.formalization.autoencoder import normative_cached_legal_ir_runtime as bound_cached
from ipfs_datasets_py.logic.formalization.autoencoder import normative_legal_ir_runtime as bound_original
from tests.unit.logic.formalization.autoencoder import test_arbitrary_native_source_cache as bound_cache_fixture
from tests.unit.logic.formalization.autoencoder import test_contextual_legal_ir_runtime as bound_contextual_fixture
from tests.unit.logic.formalization.autoencoder import test_normative_cached_legal_ir_runtime as bound_cached_fixture
from tests.unit.logic.formalization.autoencoder import test_normative_legal_ir_runtime as bound_original_fixture


@pytest.fixture
def normative_bound_no_numerics(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("metadata-only binding attempted numerical opening")
    monkeypatch.setattr(bound_contextual, "_numeric_owner", forbidden)


def _normative_bound_arbitrary(tmp_path, monkeypatch, *, duplicate=False):
    """Real occurrence/cache machinery, with only native384 admission doubled."""
    data = bound_original_fixture.make_normative(tmp_path)
    previous = bound_original_fixture.options(data)
    text = "Législation Ω must preserve the notice."
    texts = [text, text if duplicate else "New officer may examine the record."]
    document = tmp_path / "source-Ω.txt"
    prefix, separator = "Préface.\n", "\nNext.\n"
    document.write_bytes((prefix + texts[0] + separator + texts[1]).encode("utf-8"))
    artifact_pin = bound_contextual_fixture.pin(document)
    base = dict(artifact={key: artifact_pin[key] for key in ("sha256", "bytes")},
        source_kind="diagnostic", release_id="diagnostic-v1", document_id="document",
        language="en", citation="Authored occurrence fixture", normalization="identity")
    requests = []
    for index, item in enumerate(texts):
        start = len(prefix.encode("utf-8")) if index == 0 else len((prefix + texts[0] + separator).encode("utf-8"))
        requests.append(dict(id=f"new-occurrence:{index}", source_text=item,
            source={**deepcopy(base), "byte_start": start, "byte_end": start + len(item.encode("utf-8"))}))
    receipt_path = tmp_path / "native384-authored-admission.json"
    receipt_path.write_bytes(b'{"diagnostic_native_admission_double":true}')
    native_pin = bound_contextual_fixture.pin(receipt_path)
    resolver = lambda artifact: document
    _, occurrences, _ = bound_cache._requests(requests, resolver)
    admission = {(item["source_text"], bound_cache.digest(item["source"])):
        [bound_cache_fixture.record(native_pin, 384)]
        for items in occurrences.values() for item in items}
    admitted_calls = []
    def admitted(references, source_resolver):
        admitted_calls.append(deepcopy(references))
        return deepcopy(admission)
    monkeypatch.setattr(bound_cache, "_native384_records", admitted)
    cache = bound_cache.plan_arbitrary_native_source_cache(requests, dimension=384,
        native384_receipt_refs=[native_pin], source_resolver=resolver)
    assert cache["status"] == "ready" and cache["complete"] is True
    request = previous.pop("request")
    request["decoder_contract_id"] = bound_arbitrary.DECODER_CONTRACT_ID
    options = {name: deepcopy(previous[name]) for name in
        ("checkpoint_pin", "preprocessing_pin", "donor_checkpoint_pin")}
    options.update(source_cache_pin=bound_contextual_fixture.write(tmp_path / "new-source-cache.json", cache),
        source_requests_pin=bound_contextual_fixture.write(tmp_path / "new-source-requests.json", requests),
        native384_receipt_refs=[native_pin], native768_report_refs=None,
        source_artifact_pins={artifact_pin["sha256"]: artifact_pin},
        source_owner_pins={name: bound_contextual_fixture.pin(path)
                           for name, path in bound_arbitrary.source_owner_paths().items()},
        row_ids=[row["id"] for row in reversed(requests)])
    data.update(source_cache=cache, source_requests=requests, document=document,
        native_receipt_path=receipt_path, admitted_calls=admitted_calls,
        diagnostic_native_admission_double=True)
    return _normative_bound_packet(data, request, options, cache["rows"], "arbitrary")


def _normative_bound_packet(data, request, options, rows, profile):
    by_id = {row["id"]: row for row in rows}
    selected = [{"id": identifier,
        "source_sha256": hashlib.sha256(by_id[identifier]["source_text"].encode("utf-8")).hexdigest(),
        "canonical_ir": legal_target(actor="notary", action="approve", obj="notice")}
        for identifier in options["row_ids"]]
    packet = _normative_request(rows=selected)
    packet["decoder_request"] = deepcopy(request)
    return dict(data=data, request=packet, options=options, profile=profile)


def _normative_bound_fixture(tmp_path, monkeypatch, *, profile="original", dimension=384,
                            recipe="normative-wording-ce"):
    if profile == "arbitrary":
        assert dimension == 384 and recipe == "normative-wording-ce"
        return _normative_bound_arbitrary(tmp_path, monkeypatch)
    if profile == "retained":
        data = bound_cached_fixture.make_cached(tmp_path, monkeypatch, dimension, recipe)
        options = bound_cached_fixture.options(data)
        rows = data["source_cache"]["rows"]
    else:
        data = bound_original_fixture.make_normative(tmp_path, dimension, recipe)
        options = bound_original_fixture.options(data, recipe)
        rows = data["rows"]
    request = options.pop("request")
    return _normative_bound_packet(data, request, options, rows, profile)


def _normative_bound_call(packet, *, options_hash=None, request_hash=None, delegate=False):
    raw = canonical(packet["request"]).encode("utf-8")
    encoded_options = canonical(packet["options"], ascii=False).encode("utf-8")
    function = hub.preflight_normative_legal_ir_targets if delegate else compatibility.preflight_normative_legal_ir_targets
    return function(raw, expected_request_sha256=hashlib.sha256(raw).hexdigest() if request_hash is None else request_hash,
        runtime_options=packet["options"], expected_runtime_options_sha256=
        hashlib.sha256(encoded_options).hexdigest() if options_hash is None else options_hash)


def _normative_bound_track(monkeypatch, profile="original", observer=None):
    owner, name = {"original": (bound_original, "prepare_normative_legal_ir_runtime"),
        "retained": (bound_cached, "prepare_normative_cached_legal_ir_runtime"),
        "arbitrary": (bound_arbitrary, "prepare_arbitrary_native_legal_ir_runtime")}[profile]
    actual = getattr(owner, name)
    calls = []
    def tracked(request, **options):
        result = actual(request, **options)
        calls.append(dict(request=deepcopy(request), options=deepcopy(options), plan=deepcopy(result)))
        if observer is not None:
            observer(len(calls), request, options, result)
        return result
    monkeypatch.setattr(owner, name, tracked)
    return calls


def _normative_bound_assert_unqualified(report):
    _normative_assert_unqualified(report["inspection"])
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert report["opening_and_closing_preparations_matched"] is True
    assert report["source_only_preparation_calls"] == 2
    assert report["targets_forwarded_to_preparation"] is False
    assert report["targets_forwarded_to_model"] is False
    assert report["model_load_performed"] is report["inference_executed"] is False
    assert report["runtime_assets_read_by_existing_preparation"] is True
    assert report["runtime_binding"]["complete_runtime_io_contract"] is False
    assert report["runtime_binding"]["source_text_bytes_matched"] is True
    assert report["runtime_binding"]["selected_order_matched"] is True


@pytest.mark.parametrize("dimension", [384, 768])
@pytest.mark.parametrize("recipe", ["normative-wording-zero", "normative-wording-ce"])
def test_normative_bound_original_profiles_replay_exact_selected_state(tmp_path, monkeypatch,
        normative_bound_no_numerics, dimension, recipe):
    packet = _normative_bound_fixture(tmp_path, monkeypatch, dimension=dimension, recipe=recipe)
    calls = _normative_bound_track(monkeypatch)
    report = _normative_bound_call(packet)
    assert report["schema"] == "normative-legal-ir-bound-target-inspection/v1"
    assert len(calls) == 2 and calls[0] == calls[1]
    assert report["runtime_binding"]["runtime_plan_sha256"] == hashlib.sha256(
        canonical(calls[0]["plan"], ascii=False).encode("utf-8")).hexdigest()
    assert report["runtime_binding"]["artifact_receipts"]["checkpoint"] == packet["options"]["checkpoint_pin"]
    assert report["runtime_binding"]["row_receipts"] == calls[0]["plan"]["row_receipts"]
    assert report["runtime_binding"]["source_binding_scope"] == "original_saved_source_cache_rows"
    assert report["runtime_binding"]["physical_source_span_contract"] is False
    assert report["counts"]["covered"] == 2
    _normative_bound_assert_unqualified(report)


@pytest.mark.parametrize("dimension", [384, 768])
@pytest.mark.parametrize("recipe", ["normative-wording-zero", "normative-wording-ce"])
def test_normative_bound_retained_profiles_reuse_actual_cache_custody(tmp_path, monkeypatch,
        normative_bound_no_numerics, dimension, recipe):
    # make_cached declares its synthetic native-binding verifier explicitly;
    # full retained cache assembly, joins, byte custody and prepare remain real.
    packet = _normative_bound_fixture(tmp_path, monkeypatch, profile="retained", dimension=dimension, recipe=recipe)
    calls = _normative_bound_track(monkeypatch, "retained")
    report = _normative_bound_call(packet)
    assert len(calls) == 2
    assert report["runtime_binding"]["source_binding_scope"] == "retained48_source_native_cache_rows"
    assert report["runtime_binding"]["physical_source_span_contract"] is False
    assert report["runtime_binding"]["historical_evidence_receipts"] == calls[0]["plan"]["historical_evidence_receipts"]
    assert [row["id"] for row in report["runtime_binding"]["row_receipts"]] == packet["options"]["row_ids"]
    assert report["counts"]["selected"] == report["counts"]["covered"] == 3
    _normative_bound_assert_unqualified(report)


def test_normative_bound_arbitrary_source_uses_real_cache_rebuild_and_artifact_pins(tmp_path,
        monkeypatch, normative_bound_no_numerics):
    packet = _normative_bound_arbitrary(tmp_path, monkeypatch)
    before = len(packet["data"]["admitted_calls"])
    calls = _normative_bound_track(monkeypatch, "arbitrary")
    report = _normative_bound_call(packet)
    binding = report["runtime_binding"]
    assert len(calls) == 2 and len(packet["data"]["admitted_calls"]) > before
    assert binding["physical_source_span_contract"] is True
    assert binding["source_binding_scope"] == "explicit_new_source_span_occurrences_and_native_record_consistency"
    assert binding["source_artifact_receipts"] == calls[0]["plan"]["source_artifact_receipts"]
    assert binding["source_cache_binding"]["physical_occurrence_identity_preserved"] is True
    assert binding["source_cache_binding"]["encoder_execution_attested"] is False
    assert binding["runtime_options_sha256"] == hashlib.sha256(
        canonical(packet["options"], ascii=False).encode("utf-8")).hexdigest()
    assert binding["runtime_options_sha256"] != hashlib.sha256(canonical(packet["options"]).encode("utf-8")).hexdigest()
    _normative_bound_assert_unqualified(report)


def test_normative_bound_duplicate_prose_preserves_two_physical_occurrences(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_arbitrary(tmp_path, monkeypatch, duplicate=True)
    cache = packet["data"]["source_cache"]
    assert cache["rows"][0]["source_text"] == cache["rows"][1]["source_text"]
    origins = [cache["input_origins"][row["id"]][0]["source"] for row in cache["rows"]]
    assert origins[0]["artifact"] == origins[1]["artifact"]
    assert origins[0]["byte_start"] != origins[1]["byte_start"]
    report = _normative_bound_call(packet)
    receipts = report["runtime_binding"]["row_receipts"]
    assert [row["id"] for row in receipts] == ["new-occurrence:1", "new-occurrence:0"]
    assert receipts[0]["source_sha256"] == receipts[1]["source_sha256"]
    assert report["counts"]["selected"] == report["counts"]["covered"] == 2
    assert report["runtime_binding"]["source_cache_binding"]["selected_occurrences"] == 2
    _normative_bound_assert_unqualified(report)


def test_normative_bound_prepare_arguments_are_source_only_at_both_endpoints(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    packet["request"]["rows"][0]["canonical_ir"] = legal_target(actor="private-label-sentinel")
    calls = _normative_bound_track(monkeypatch)
    report = _normative_bound_call(packet)
    assert len(calls) == 2
    for call in calls:
        assert set(call["request"]) == set(packet["request"]["decoder_request"])
        assert "request" not in call["options"] and "rows" not in call["options"]
        assert "private-label-sentinel" not in canonical(call)
        assert all(set(row) == {"id", "source_text", "input"} for row in call["plan"]["source_inputs"]["rows"])
    assert report["inspection"]["rows"][0]["status"] == "incompatible"
    _normative_bound_assert_unqualified(report)


def test_normative_bound_hub_delegate_matches_the_public_owner(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    assert _normative_bound_call(packet, delegate=True) == _normative_bound_call(packet)


def test_normative_bound_pending_unsupported_and_oov_labels_keep_population(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch, profile="retained")
    labels = [None, {"rules": []}, legal_target(actor="statutory-person")]
    for row, label in zip(packet["request"]["rows"], labels):
        row["canonical_ir"] = label
    report = _normative_bound_call(packet)
    assert [row["status"] for row in report["inspection"]["rows"]] == ["pending", "unsupported", "incompatible"]
    assert report["counts"] == dict(selected=3, covered=0, incompatible=1, unsupported=1,
        pending=1, with_oov=1, over_limit=0)
    assert len(report["runtime_binding"]["row_receipts"]) == 3
    _normative_bound_assert_unqualified(report)


def test_normative_bound_label_changes_do_not_change_selected_runtime_plan(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    first = _normative_bound_call(packet)
    packet["request"]["rows"][0]["canonical_ir"] = None
    packet["request"]["rows"][1]["canonical_ir"] = legal_target(actor="approve", action="notary", obj="notice")
    second = _normative_bound_call(packet)
    assert first["runtime_binding"] == second["runtime_binding"]
    assert first["inspection"]["request_sha256"] != second["inspection"]["request_sha256"]
    assert [row["status"] for row in second["inspection"]["rows"]] == ["pending", "covered"]
    _normative_bound_assert_unqualified(second)


def test_normative_bound_inputs_and_returned_receipts_are_detached(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    before = deepcopy((packet["request"], packet["options"]))
    first = _normative_bound_call(packet)
    assert (packet["request"], packet["options"]) == before
    first["runtime_binding"]["row_receipts"][0]["id"] = "caller-mutation"
    first["counts"]["covered"] = -1
    first["authority"]["semantic_representability_verified"] = True
    second = _normative_bound_call(packet)
    assert second["runtime_binding"]["row_receipts"][0]["id"] == packet["options"]["row_ids"][0]
    assert second["counts"]["covered"] == 2
    _normative_bound_assert_unqualified(second)


def test_normative_bound_report_contains_receipts_without_source_or_vector_payloads(tmp_path,
        monkeypatch, normative_bound_no_numerics):
    packet = _normative_bound_arbitrary(tmp_path, monkeypatch)
    report = _normative_bound_call(packet)
    pending = [report]
    forbidden = {"source_text", "input", "vector", "contexts", "canonical_ir", "model_state"}
    while pending:
        item = pending.pop()
        if type(item) is dict:
            assert not forbidden.intersection(item)
            if "source_inputs" in item:
                receipt = item["source_inputs"]
                assert type(receipt) is dict and set(receipt) == {"path", "bytes", "sha256"}
                assert type(receipt["path"]) is str and Path(receipt["path"]).is_absolute()
                assert type(receipt["bytes"]) is int and receipt["bytes"] > 0
                assert type(receipt["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"])
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    for row in packet["data"]["source_cache"]["rows"]:
        assert row["source_text"] not in canonical(report, ascii=False)
    _normative_bound_assert_unqualified(report)


def test_normative_bound_valid_but_wrong_source_hash_refuses_after_opening(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    packet["request"]["rows"][0]["source_sha256"] = "0" * 64
    calls = _normative_bound_track(monkeypatch)
    with pytest.raises(compatibility.TargetCompatibilityError):
        _normative_bound_call(packet)
    assert len(calls) == 1


def test_normative_bound_hashes_cannot_be_reassigned_between_ordered_source_ids(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    rows = packet["request"]["rows"]
    rows[0]["source_sha256"], rows[1]["source_sha256"] = rows[1]["source_sha256"], rows[0]["source_sha256"]
    calls = _normative_bound_track(monkeypatch)
    with pytest.raises(compatibility.TargetCompatibilityError):
        _normative_bound_call(packet)
    assert len(calls) == 1


@pytest.mark.parametrize("damage", ["wrong_options_hash", "uppercase_options_hash", "typed_options_hash",
    "target_option", "request_option", "missing_option", "reordered_ids", "missing_id"])
def test_normative_bound_closed_options_and_independent_pin_refuse_before_prepare(tmp_path, monkeypatch,
        normative_bound_no_numerics, damage):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    expected = None
    if damage == "wrong_options_hash": expected = "0" * 64
    elif damage == "uppercase_options_hash": expected = "A" * 64
    elif damage == "typed_options_hash": expected = 17
    elif damage == "target_option": packet["options"]["canonical_ir"] = legal_target()
    elif damage == "request_option": packet["options"]["request"] = packet["request"]["decoder_request"]
    elif damage == "missing_option": del packet["options"]["source_contexts_pin"]
    elif damage == "reordered_ids": packet["options"]["row_ids"].reverse()
    else: packet["options"]["row_ids"].pop()
    calls = _normative_bound_track(monkeypatch)
    with pytest.raises(compatibility.TargetCompatibilityError):
        _normative_bound_call(packet, options_hash=expected)
    assert calls == []


@pytest.mark.parametrize("damage", ["tuple", "surrogate", "nonfinite"])
def test_normative_bound_runtime_options_are_plain_finite_utf8_json(tmp_path, monkeypatch,
        normative_bound_no_numerics, damage):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    if damage == "tuple": packet["options"]["row_ids"] = tuple(packet["options"]["row_ids"])
    elif damage == "surrogate": packet["options"]["checkpoint_pin"]["path"] = "\ud800"
    else: packet["options"]["deadline_seconds"] = float("inf")
    calls = _normative_bound_track(monkeypatch)
    raw = canonical(packet["request"]).encode("utf-8")
    with pytest.raises(compatibility.TargetCompatibilityError):
        compatibility.preflight_normative_legal_ir_targets(raw,
            expected_request_sha256=hashlib.sha256(raw).hexdigest(), runtime_options=packet["options"],
            expected_runtime_options_sha256="0" * 64)
    assert calls == []


def test_normative_bound_changed_raw_request_refuses_before_runtime_preparation(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    calls = _normative_bound_track(monkeypatch)
    with pytest.raises(compatibility.TargetCompatibilityError):
        _normative_bound_call(packet, request_hash="0" * 64)
    assert calls == []


@pytest.mark.parametrize("artifact", ["source_rows", "source_contexts", "checkpoint",
    "retained_cache", "physical_source", "native_receipt"])
def test_normative_bound_closing_preparation_rejects_cache_or_source_drift(tmp_path, monkeypatch,
        normative_bound_no_numerics, artifact):
    profile = "retained" if artifact == "retained_cache" else "arbitrary" if artifact in ("physical_source", "native_receipt") else "original"
    packet = _normative_bound_fixture(tmp_path, monkeypatch, profile=profile)
    option = {"source_rows": "source_inputs_pin", "source_contexts": "source_contexts_pin",
        "checkpoint": "checkpoint_pin", "retained_cache": "source_cache_pin"}.get(artifact)
    path = Path(packet["options"][option]["path"]) if option else packet["data"][
        "document" if artifact == "physical_source" else "native_receipt_path"]
    actual_inspect = compatibility.inspect_normative_legal_ir_targets
    inspected = []
    def inspect_then_drift(*args, **kwargs):
        result = actual_inspect(*args, **kwargs)
        path.write_bytes(path.read_bytes() + b" ")
        inspected.append(True)
        return result
    monkeypatch.setattr(compatibility, "inspect_normative_legal_ir_targets", inspect_then_drift)
    calls = _normative_bound_track(monkeypatch, profile)
    with pytest.raises(compatibility.TargetCompatibilityError):
        _normative_bound_call(packet)
    assert inspected == [True] and len(calls) == 1


def test_normative_bound_closing_observer_cannot_rewrite_opening_plan_receipts(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    retained = []
    def observer(index, request, options, result):
        if index == 1:
            retained.append(result)
        else:
            retained[0]["input_transform_sha256"] = "0" * 64
    calls = _normative_bound_track(monkeypatch, observer=observer)
    with pytest.raises(compatibility.TargetCompatibilityError):
        _normative_bound_call(packet)
    assert len(calls) == 2


def test_normative_bound_failed_genuine_opening_does_not_inspect_labels(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    path = Path(packet["options"]["checkpoint_pin"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    inspected = []
    actual_inspect = compatibility.inspect_normative_legal_ir_targets
    def inspect(*args, **kwargs):
        inspected.append(True)
        return actual_inspect(*args, **kwargs)
    monkeypatch.setattr(compatibility, "inspect_normative_legal_ir_targets", inspect)
    with pytest.raises(compatibility.TargetCompatibilityError):
        _normative_bound_call(packet)
    assert inspected == []


def test_normative_bound_failed_pure_inspection_stops_before_closing_preparation(tmp_path, monkeypatch,
        normative_bound_no_numerics):
    packet = _normative_bound_fixture(tmp_path, monkeypatch)
    actual_inspect = compatibility.inspect_normative_legal_ir_targets
    def inspect_then_refuse(*args, **kwargs):
        actual_inspect(*args, **kwargs)
        raise compatibility.TargetCompatibilityError("controlled evaluator refusal after genuine pure inspection")
    monkeypatch.setattr(compatibility, "inspect_normative_legal_ir_targets", inspect_then_refuse)
    calls = _normative_bound_track(monkeypatch)
    with pytest.raises(compatibility.TargetCompatibilityError):
        _normative_bound_call(packet)
    assert len(calls) == 1


# These appended source-preflight controls deliberately replace the public role
# inspector and receipt conditioner with authored metadata doubles. The source
# factory, bounded snapshots, 537-token codec, context validator and BOS budget
# policy remain genuine. No checkpoint, encoder, numerical model or legal claim
# is qualified by the doubled reports.
def _compact_bos_authored_documents():
    obj = dict(arguments=[], kind="atomic", name="Object", schema_version="syntax-logic-sort/v1")
    boolean = dict(arguments=[], kind="bool", name="Bool", schema_version="syntax-logic-sort/v1")
    def identity(namespace, value):
        return dict(interface="LogicIdentityNamespaces@1", namespace=namespace,
            schema_version="logic-identity-namespaces/v1", value=value, version="1.0.0")
    names = ["FixtureHand", "FixtureTake", "FixtureMark"]
    symbols = [dict(domain=[deepcopy(obj), deepcopy(obj)], kind="predicate", metadata={}, name=name,
        range=deepcopy(boolean), schema_version="syntax-symbol-declaration/v1") for name in names]
    context = dict(schema="legal-relational-compact-context/v1",
        argument_roles=[dict(symbol=name, roles=["first", "second"]) for name in names],
        signature=dict(family=identity("family", "tdfol"), features=[], interface="LogicSignature@1", metadata={},
            profile=identity("profile", "tdfol_default"), schema_version="syntax-logic-signature/v1",
            sorts=[boolean, obj], symbols=symbols))
    def atom(index, left, right):
        return ["predicate", index, [["variable", left], ["variable", right]]]
    document = dict(schema="legal-relational-compact-content/v1", tree=["forall", 0,
        ["exists", 1, ["forall", 2, ["and", ["extension", "F", ["implies",
            atom(0, 0, 1), atom(1, 1, 0)]], atom(2, 2, 1)]]]])
    return context, document


class _CompactBOSMetadataDoubles:
    """Real source factory/grammar with visibly authored inspector/receipt seams."""

    def __init__(self, tmp_path, monkeypatch, *, rows=1, maximum=100):
        from ipfs_datasets_py.logic.formalization.autoencoder import (
            legal_compact_content_role_trained_runtime_v1 as role,
            legal_compact_content_source_binding_v1 as source,
            legal_compact_content_tokens_v1 as tokens,
            legal_compact_content_completion_budget_v1 as budget,
            legal_compact_content_role_budget_runtime_v1 as consumer,
            legal_compact_content_prepared_runtime_v3 as prepared,
        )
        self.role, self.source, self.tokens, self.budget = role, source, tokens, budget
        self.monkeypatch = monkeypatch
        self.inspect_calls, self.source_calls, self.prefix_calls, self.target_calls = [], [], [], []
        self.on_inspect = self.on_source = None
        self.statuses = {}
        context, self.document = _compact_bos_authored_documents()
        self.context_raw = canonical(context, ascii=False).encode()
        self.target_raw = canonical(self.document, ascii=False).encode()
        self.codec = tokens.build_compact_content_token_codec_v1()
        self.codec_sha = tokens.compact_content_token_codec_sha256(self.codec)
        pieces = JSON_TOKEN.findall(self.target_raw.decode())
        assert "".join(pieces).encode() == self.target_raw and len(pieces) == 99
        positions = {spelling: index for index, spelling in enumerate(self.codec["vocabulary"])}
        self.authored_ids = [1, *(positions[piece] for piece in pieces), 2]
        assert len(self.authored_ids) == 101
        self.checkpoint = {"codec": deepcopy(self.codec), "authored_checkpoint_double": ["not a retained model"]}
        self.checkpoint_sha = self.sha(canonical(self.checkpoint, ascii=False).encode())
        self.policy_sha = "e" * 64
        text, separator = "Authored source clause.", "\n#\n"
        artifact_raw = separator.join([text] * rows).encode()
        self.artifact = tmp_path / "authored-physical-source.txt"
        self.artifact.write_bytes(artifact_raw)
        artifact = dict(bytes=len(artifact_raw), sha256=self.sha(artifact_raw))
        self.receipt = tmp_path / "authored-conditioner-double.json"
        self.receipt.write_bytes(b'{"authored_receipt_double":true}')
        receipt_raw = self.receipt.read_bytes()
        ref = dict(path=str(self.receipt), bytes=len(receipt_raw), sha256=self.sha(receipt_raw))
        selected = []
        for index in range(rows):
            identifier = "authored-occurrence:" + str(index)
            start = index * len((text + separator).encode())
            span = dict(artifact=deepcopy(artifact), source_kind="diagnostic", release_id="authored-release-v1",
                document_id="authored-document", language="en", citation="Authored source fixture",
                normalization="identity", byte_start=start, byte_end=start + len(text.encode()))
            payload = dict(source=span, title="Authored source", section="1", text=text, citation=span["citation"])
            input_id = "sha256:" + self.sha(canonical({"schema": "source-embedding-input-v1", **payload}).encode())
            request = dict(occurrence_id=identifier, input=dict(input_id=input_id, **payload))
            selected.append(dict(id=identifier, source_request=request,
                expected_source_request_sha256=self.sha(canonical(request, ascii=False).encode()),
                input_id=input_id, receipt_ref=deepcopy(ref), context_raw_utf8=self.context_raw.decode(),
                expected_context_sha256=self.sha(self.context_raw), context_origin="authored_fixture",
                target_content_raw_utf8=self.target_raw.decode(), expected_target_content_sha256=self.sha(self.target_raw)))
        self.request = dict(schema="compact-role-bos-source-preflight-request/v1", max_new_tokens=maximum, rows=selected)
        self.actual_prefix = budget.allowed_token_ids
        self.actual_encode = tokens.encode_compact_content_tokens_v1
        monkeypatch.setattr(role, "inspect", self.inspect)
        monkeypatch.setattr(source, "prepare_compact_source_conditioning_v1", self.prepare)
        monkeypatch.setattr(budget, "allowed_token_ids", self.prefix)
        monkeypatch.setattr(tokens, "encode_compact_content_tokens_v1", self.encode)
        def forbidden(*_args, **_kwargs):
            raise AssertionError("metadata preflight attempted numerical dispatch")
        monkeypatch.setattr(role, "generate", forbidden)
        monkeypatch.setattr(consumer, "generate", forbidden)
        monkeypatch.setattr(consumer, "generate_from_bos_v2", forbidden)
        monkeypatch.setattr(prepared, "_PreparedModel", forbidden)

    @staticmethod
    def sha(raw):
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def value_sha(cls, value):
        return cls.sha(canonical(value, ascii=False).encode())

    def inspect(self, checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
        self.inspect_calls.append(deepcopy(dict(checkpoint=checkpoint,
            expected_checkpoint_sha256=expected_checkpoint_sha256, expected_policy_sha256=expected_policy_sha256)))
        if self.value_sha(checkpoint) != expected_checkpoint_sha256 or expected_policy_sha256 != self.policy_sha:
            raise ValueError("authored role inspector pin mismatch")
        report = dict(schema=self.role.INSPECT_SCHEMA, profile=self.role.PROFILE,
            checkpoint_sha256=expected_checkpoint_sha256, objective_policy_sha256=expected_policy_sha256,
            codec_sha256=self.codec_sha, weights_sha256="a" * 64,
            model_restore_count=0, numerical_forward_count=0, checkpoint_inspection_count=1,
            model_executed=False, optimizer_constructed=False, optimizer_state_restored=False,
            training_executed=False, target_access_for_checkpoint_validation=True,
            serving_view_schema=self.role.SERVING_SCHEMA, serving_view_contains_training_targets=False,
            serving_view_contains_optimizer_state=False, authority={"authored_double_grants_no_authority": False},
            training_mask=0, evaluation_gold_mask=0)
        if self.on_inspect is not None:
            self.on_inspect(len(self.inspect_calls), checkpoint, report)
        return report

    def prepare(self, source_request, receipt_ref, *, expected_source_request_sha256, input_id, source_resolver):
        import struct
        self.source_calls.append(deepcopy(dict(source_request=source_request, receipt_ref=receipt_ref,
            expected_source_request_sha256=expected_source_request_sha256, input_id=input_id)))
        if (self.value_sha(source_request) != expected_source_request_sha256
                or source_request["input"]["input_id"] != input_id):
            raise ValueError("authored conditioner source-request pin mismatch")
        item = source_request["input"]
        status = self.statuses.get(source_request["occurrence_id"], "embedded")
        vector = [0.125] * 384 if status == "embedded" else None
        bits = struct.pack(">384f", *vector) if vector is not None else None
        binding = dict(schema=self.source.ENCODER_BINDING_SCHEMA, conditioning_space="raw_native_gte_small384",
            model={"id": "thenlper/gte-small", "revision": "17e1f347d17fe144873b1201da91788898c639cd", "dimension": 384},
            model_assets=[], producer={"authored_metadata_double": True}, execution={"authored_metadata_double": True})
        report = dict(schema=self.source.CONDITIONING_SCHEMA, profile=self.source.CONDITIONING_PROFILE, status=status,
            occurrence_id=source_request["occurrence_id"], input_id=input_id, input=deepcopy(item),
            source_request_sha256=expected_source_request_sha256, source_sha256=self.sha(item["text"].encode()),
            source_span=deepcopy(item["source"]), receipt=deepcopy(receipt_ref),
            encoder_binding=binding, encoder_binding_sha256=self.value_sha(binding),
            conditioning=vector, conditioning_sha256=self.value_sha(vector) if vector is not None else None,
            native_vector_bits_sha256=self.sha(bits) if bits is not None else None,
            source_bytes_verified=status != "missing_input", source_receipt_binding_verified=status == "embedded",
            native_execution_record_present=True, encoder_executed_by_adapter=False,
            runtime_computation_proven=False, source_encoder_authenticated=False,
            authority={"authored_double_grants_no_authority": False}, training_mask=0, evaluation_gold_mask=0)
        if self.on_source is not None:
            self.on_source(len(self.source_calls), source_request, report)
        return report

    def prefix(self, prefix_ids, context_raw, **options):
        self.prefix_calls.append(dict(prefix_ids=deepcopy(prefix_ids), context_raw=context_raw, options=deepcopy(options)))
        return self.actual_prefix(prefix_ids, context_raw, **options)

    def encode(self, content_raw, context_raw, **options):
        self.target_calls.append(dict(content_raw=content_raw, context_raw=context_raw, options=deepcopy(options)))
        return self.actual_encode(content_raw, context_raw, **options)

    def call(self, *, delegate=False, request_sha=None, checkpoint_sha=None):
        raw = canonical(self.request, ascii=False).encode()
        function = hub.preflight_compact_role_bos_sources if delegate else compatibility.preflight_compact_role_bos_sources
        return function(raw, self.checkpoint, expected_request_sha256=self.sha(raw) if request_sha is None else request_sha,
            expected_checkpoint_sha256=self.checkpoint_sha if checkpoint_sha is None else checkpoint_sha,
            expected_policy_sha256=self.policy_sha, source_resolver=lambda _descriptor: self.artifact.read_bytes())

    def assert_no_label_leak(self):
        targets = [row["target_content_raw_utf8"] for row in self.request["rows"]
                   if row["target_content_raw_utf8"] is not None]
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child)
        for call in self.inspect_calls + self.source_calls:
            offered_strings = list(strings(call))
            assert all(target not in value for target in targets for value in offered_strings)
            assert "target_content_raw_utf8" not in offered_strings
        for call in self.prefix_calls:
            assert call["prefix_ids"] == [1]
            assert call["context_raw"] == self.context_raw
            assert call["options"]["remaining_new_tokens"] == self.request["max_new_tokens"]
            assert "content_raw" not in call["options"] and "target" not in call["options"]


def _compact_bos_assert_inspection_only(report):
    assert report["generation_ready"] is False and report["execution_packet"] is None
    assert report["model_restore_count"] == report["numerical_forward_count"] == 0
    assert report["encoder_executed"] is report["training_executed"] is False
    assert report["targets_forwarded_to_runtime"] is False
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert "conditioning_space_training_compatibility_unqualified" in report["blockers"]
    assert "context_permission_unverified" in report["blockers"]


def test_compact_bos_source_preflight_real_101_id_capacity_with_authored_metadata_only(tmp_path, monkeypatch):
    import inspect
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    parameters = inspect.signature(compatibility.preflight_compact_role_bos_sources).parameters
    assert set(parameters) == {"request_raw", "checkpoint", "expected_request_sha256",
        "expected_checkpoint_sha256", "expected_policy_sha256", "source_resolver"}
    report = fixture.call()
    _compact_bos_assert_inspection_only(report)
    assert report["schema"] == "compact-role-bos-source-preflight/v1"
    assert report["counts"]["rows"] == report["counts"]["encoded_targets"] == 1
    assert report["rows"][0]["target"]["disposition"] == "encoded"
    assert report["rows"][0]["target"]["total_ids"] == 101
    assert report["rows"][0]["target"]["new_ids"] == 100
    assert report["rows"][0]["target"]["within_allowance"] is True
    assert report["rows"][0]["target"]["error"] is None
    assert report["rows"][0]["target"]["original_content_raw_sha256"] == fixture.sha(fixture.target_raw)
    assert report["rows"][0]["target"]["canonical_content_sha256"] == fixture.sha(fixture.target_raw)
    assert report["rows"][0]["target"]["target_ids_sha256"] == fixture.value_sha(fixture.authored_ids)
    assert report["consumer"]["prefix_ids"] == [1] and report["consumer"]["prefix_origin"] == "bos_seed"
    assert report["consumer"]["max_total_ids"] == 512 and report["consumer"]["vocabulary_size"] == 537
    assert report["consumer"]["max_new_tokens"] == 100 and report["consumer"]["max_report_bytes"] == 16 * 1024**2
    assert report["consumer"]["codec_sha256"] == fixture.codec_sha
    assert report["checkpoint_inspection_calls"] == len(fixture.inspect_calls) == 2
    assert report["source_only_preparation_calls"] == len(fixture.source_calls) == 2
    assert report["opening_and_closing_preparations_matched"] is True
    assert fixture.target_calls and fixture.target_calls[0]["content_raw"] == fixture.target_raw
    fixture.assert_no_label_leak()


def test_compact_bos_source_preflight_99_allowance_does_not_fit_100_new_target_ids(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch, maximum=99)
    report = fixture.call()
    target = report["rows"][0]["target"]
    assert target["disposition"] == "encoded" and target["new_ids"] == 100
    assert target["within_allowance"] is False and report["counts"]["targets_over_allowance"] == 1
    assert report["rows"][0]["prefix_report"]["remaining_new_tokens"] == 99
    _compact_bos_assert_inspection_only(report)
    fixture.assert_no_label_leak()


def test_compact_bos_source_preflight_preserves_equal_prose_distinct_origins_and_unavailable_rows(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch, rows=4)
    fixture.statuses = {"authored-occurrence:2": "missing_input", "authored-occurrence:3": "token_limit_exceeded"}
    report = fixture.call()
    assert [row["id"] for row in report["rows"]] == [row["id"] for row in fixture.request["rows"]]
    sources = [row["source"] for row in report["rows"]]
    assert len({row["source_sha256"] for row in sources}) == 1
    assert len({row["input_id"] for row in sources}) == 4
    assert len({row["source_span"]["byte_start"] for row in sources}) == 4
    assert sources[0]["conditioning_sha256"] == sources[1]["conditioning_sha256"]
    assert [row["status"] for row in sources] == ["embedded", "embedded", "missing_input", "token_limit_exceeded"]
    assert [row["conditioning_available"] for row in sources] == [True, True, False, False]
    assert all(sources[index]["conditioning_sha256"] is sources[index]["native_vector_bits_sha256"] is None for index in (2, 3))
    assert report["counts"]["rows"] == 4 and report["counts"]["embedded"] == report["counts"]["unavailable"] == 2
    assert report["source_only_preparation_calls"] == len(fixture.source_calls) == 8
    _compact_bos_assert_inspection_only(report)
    fixture.assert_no_label_leak()


def test_compact_bos_source_preflight_null_target_preserves_pending_unknown_metrics(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    row = fixture.request["rows"][0]
    row["target_content_raw_utf8"] = row["expected_target_content_sha256"] = None
    report = fixture.call()
    target = report["rows"][0]["target"]
    assert target["disposition"] == "pending" and target["error"] is None
    assert all(target[key] is None for key in ("total_ids", "new_ids", "within_allowance",
        "original_content_raw_sha256", "canonical_content_sha256", "target_ids_sha256"))
    assert report["counts"]["pending_targets"] == 1 and fixture.target_calls == []
    _compact_bos_assert_inspection_only(report)


@pytest.mark.parametrize("kind", ["counted_profile", "overflow"])
def test_compact_bos_source_preflight_unencoded_labels_remain_explicit_unknowns(kind, tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    if kind == "counted_profile":
        # An explicit foreign counted-profile shape, not a claimed7214 replay.
        document = {"schema": "legal-counted-compact-content/v1", "tree": ["equal", ["variable", 0], ["variable", 1]]}
    else:
        # Balanced repetition exceeds512 lexical IDs without a deep JSON chain.
        tree = deepcopy(fixture.document["tree"][2][2][2])
        for _ in range(3):
            tree = ["and", deepcopy(tree), deepcopy(tree)]
        document = {"schema": "legal-relational-compact-content/v1",
            "tree": ["forall", 0, ["exists", 1, ["forall", 2, tree]]]}
    raw = canonical(document, ascii=False).encode()
    if kind == "overflow":
        assert len(JSON_TOKEN.findall(raw.decode())) + 2 > 512
    row = fixture.request["rows"][0]
    row["target_content_raw_utf8"], row["expected_target_content_sha256"] = raw.decode(), fixture.sha(raw)
    report = fixture.call()
    target = report["rows"][0]["target"]
    assert target["disposition"] == "not_encoded" and set(target["error"]) == {"class", "message"}
    assert target["error"]["class"] and target["error"]["message"]
    assert all(target[key] is None for key in ("total_ids", "new_ids", "within_allowance"))
    assert target["original_content_raw_sha256"] == fixture.sha(raw)
    assert target["canonical_content_sha256"] is target["target_ids_sha256"] is None
    assert report["counts"]["not_encoded_targets"] == 1
    assert report["counts"]["targets_within_allowance"] == report["counts"]["targets_over_allowance"] == 0
    _compact_bos_assert_inspection_only(report)
    fixture.assert_no_label_leak()


def test_compact_bos_source_preflight_target_derived_context_is_a_declaration_not_blind_permission(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    fixture.request["rows"][0]["context_origin"] = "target_derived_label"
    report = fixture.call()
    assert report["rows"][0]["context_origin"] == "target_derived_label"
    assert report["rows"][0]["context_raw_sha256"] == fixture.sha(fixture.context_raw)
    assert report["authority"]["context_permission_verified"] is False
    assert report["checkpoint_inspection"]["target_access_for_checkpoint_validation"] is True
    _compact_bos_assert_inspection_only(report)
    fixture.assert_no_label_leak()


def test_compact_bos_source_preflight_returns_detached_metadata_without_execution_inputs(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    before = deepcopy((fixture.request, fixture.checkpoint))
    report = fixture.call()
    assert (fixture.request, fixture.checkpoint) == before
    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)
    offered_keys = set(keys(report))
    assert {"conditioning", "embedding", "target_content_raw_utf8", "context_raw_utf8"}.isdisjoint(offered_keys)
    assert report["rows"][0]["source"]["input"] == fixture.request["rows"][0]["source_request"]["input"]
    report["rows"][0]["source"]["input"]["text"] = "detached report mutation"
    report["rows"][0]["source"]["source_span"]["byte_start"] += 1
    report["checkpoint_inspection"]["weights_sha256"] = "f" * 64
    assert (fixture.request, fixture.checkpoint) == before
    _compact_bos_assert_inspection_only(report)


@pytest.mark.parametrize("field", ["checkpoint", "context", "target", "source_request", "request"])
def test_compact_bos_source_preflight_independent_hash_mismatches_refuse(field, tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    kwargs = {}
    if field in ("checkpoint", "request"):
        kwargs[field + "_sha"] = "0" * 64
    else:
        key = {"context": "expected_context_sha256", "target": "expected_target_content_sha256",
               "source_request": "expected_source_request_sha256"}[field]
        fixture.request["rows"][0][key] = "0" * 64
    with pytest.raises(compatibility.TargetCompatibilityError):
        fixture.call(**kwargs)
    fixture.assert_no_label_leak()


@pytest.mark.parametrize("maximum", [True, 1.0, 0, 512], ids=["boolean", "float", "zero", "512"])
def test_compact_bos_source_preflight_rejects_invalid_allowance_before_producer_calls(maximum, tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch, maximum=maximum)
    with pytest.raises(compatibility.TargetCompatibilityError):
        fixture.call()
    assert fixture.inspect_calls == fixture.source_calls == fixture.prefix_calls == fixture.target_calls == []


def test_compact_bos_source_preflight_failed_opening_does_not_inspect_new_labels(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    primary = ValueError("authored role opening refusal")
    def refuse(_count, _checkpoint, _report):
        raise primary
    fixture.on_inspect = refuse
    with pytest.raises(compatibility.TargetCompatibilityError) as raised:
        fixture.call()
    assert raised.value.__cause__ is primary or raised.value is primary
    assert len(fixture.inspect_calls) == 1 and fixture.source_calls == fixture.target_calls == []


@pytest.mark.parametrize("producer", ["checkpoint", "conditioning"])
def test_compact_bos_source_preflight_changed_closing_producer_report_refuses(producer, tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    if producer == "checkpoint":
        def change(count, _checkpoint, report):
            if count == 2:
                report["weights_sha256"] = "f" * 64
        fixture.on_inspect = change
    else:
        def change(count, _request, report):
            import struct
            if count == 2:
                report["conditioning"][0] = 0.25
                report["conditioning_sha256"] = fixture.value_sha(report["conditioning"])
                report["native_vector_bits_sha256"] = fixture.sha(struct.pack(">384f", *report["conditioning"]))
        fixture.on_source = change
    with pytest.raises(compatibility.TargetCompatibilityError):
        fixture.call()
    fixture.assert_no_label_leak()


def test_compact_bos_source_preflight_caller_and_offered_producer_input_mutations_are_detected(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    checkpoint_before = deepcopy(fixture.checkpoint)
    def change(_count, _checkpoint, _report):
        fixture.checkpoint["authored_checkpoint_double"].append("changed during producer callback")
    fixture.on_inspect = change
    with pytest.raises(compatibility.TargetCompatibilityError):
        fixture.call()
    assert fixture.source_calls == fixture.target_calls == []
    fixture.checkpoint.clear()
    fixture.checkpoint.update(checkpoint_before)
    fixture.on_inspect = None
    request_before = deepcopy(fixture.request)
    def mutate_offered(_count, offered, _report):
        offered["input"]["text"] = "changed producer argument"
    fixture.on_source = mutate_offered
    with pytest.raises(compatibility.TargetCompatibilityError):
        fixture.call()
    assert fixture.request == request_before and len(fixture.source_calls) == 1 and fixture.target_calls == []


def test_compact_bos_source_preflight_changed_dependency_pin_is_not_a_new_profile(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    def change(_count, _checkpoint, _report):
        pins = list(compatibility._COMPACT_ROLE_PINS)
        key, name, size, _digest = pins[0]
        pins[0] = (key, name, size, "0" * 64)
        monkeypatch.setattr(compatibility, "_COMPACT_ROLE_PINS", tuple(pins))
    fixture.on_inspect = change
    with pytest.raises(compatibility.TargetCompatibilityError):
        fixture.call()
    assert fixture.target_calls == []


def test_compact_bos_source_preflight_primary_interrupt_survives_a_closing_origin_failure(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    primary = KeyboardInterrupt("authored conditioner interruption")
    def interrupt(_count, _request, _report):
        monkeypatch.setattr(fixture.role, "__file__", str(Path(fixture.role.__file__).with_name("changed-origin.py")))
        raise primary
    fixture.on_source = interrupt
    with pytest.raises(KeyboardInterrupt) as raised:
        fixture.call()
    assert raised.value is primary and fixture.target_calls == []
    assert any("closing" in note.lower() for note in getattr(primary, "__notes__", []))


def test_compact_bos_source_preflight_genuine_factory_and_hub_delegate_agree(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    owners, observations = compatibility._compact_role_owners()
    assert owners["role"] is fixture.role and owners["source"] is fixture.source
    assert owners["tokens"] is fixture.tokens and owners["budget"] is fixture.budget
    assert len(observations) == 7 and len({pin["path"] for pin, _witness in observations}) == 7
    for pin, _witness in observations:
        raw = Path(pin["path"]).read_bytes()
        assert len(raw) == pin["bytes"] and fixture.sha(raw) == pin["sha256"]
    direct, delegated = fixture.call(), fixture.call(delegate=True)
    assert direct == delegated
    assert direct["dependency_pins"] == [pin for pin, _witness in observations]
    _compact_bos_assert_inspection_only(delegated)
    fixture.assert_no_label_leak()


def test_compact_bos_source_preflight_closed_rows_never_repair_missing_or_duplicate_population(tmp_path, monkeypatch):
    fixture = _CompactBOSMetadataDoubles(tmp_path, monkeypatch)
    original = deepcopy(fixture.request)
    for damage in ("extra_row_key", "missing_row_key", "duplicate_row", "empty_rows"):
        fixture.request = deepcopy(original)
        row = fixture.request["rows"][0]
        if damage == "extra_row_key":
            row["target_for_runtime"] = row["target_content_raw_utf8"]
        elif damage == "missing_row_key":
            del row["context_origin"]
        elif damage == "duplicate_row":
            fixture.request["rows"].append(deepcopy(row))
        else:
            fixture.request["rows"] = []
        with pytest.raises(compatibility.TargetCompatibilityError):
            fixture.call()
    assert fixture.inspect_calls == fixture.source_calls == fixture.prefix_calls == fixture.target_calls == []


# Counted-prefix inspection is a finite singleton-language observation. The
# independently authored fixture below is a declaration, never statutory gold,
# a checkpoint, a learned target population or an inference-context permission.
_COUNTED_PREFIX_SCHEMA = "legal-counted-content-prefix-inspection/v1"
_COUNTED_PREFIX_PROFILE = "authored-counted28-singleton-prefix-inspection/v1"
_COUNTED_PREFIX_FIELDS = {
    "schema", "profile", "status", "reason", "offered_ids", "allowed_token_ids",
    "matched_prefix_length", "completion_tokens_remaining", "remaining_token_slots",
    "max_sequence_tokens", "canonical_sequence_token_count", "canonical_sequence_sha256",
    "content_sha256", "context_sha256", "context_raw_sha256", "codec_sha256",
    "profile_is_singleton", "admissible_content_count", "source_dependence_established",
    "context_origin", "permitted_inference_context_verified", "numerical_runtime_available",
    "checkpoint_compatibility_verified", "complete_candidate", "producer_pins", "authority",
    "training_mask", "evaluation_gold_mask", "limitations",
}


def _counted_prefix_wire(value):
    return canonical(value, ascii=False).encode("utf-8")


def _counted_prefix_sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _counted_prefix_documents():
    def variable(index):
        return ["variable", index]
    def left_fold(kind, terms):
        result = terms[0]
        for term in terms[1:]:
            result = [kind, result, term]
        return result
    members = [["predicate", 0, [variable(i), variable(0), variable(1)]] for i in range(2, 6)]
    pairs = [(2, 3), (2, 4), (2, 5), (3, 4), (3, 5), (4, 5)]
    equalities = [["equality", variable(left), variable(right)] for left, right in pairs]
    root = ["implies", left_fold("and", members), left_fold("or", equalities)]
    sorts = ["EventFrame", "TimeFrame", "Object", "Object", "Object", "Object"]
    for index in reversed(range(6)):
        root = ["forall", index, sorts[index], root]
    content = {"schema": "legal-counted-compact-content/v1", "tree": root}
    context = {"schema": "legal-counted-compact-context/v1", "sorts": ["Object", "EventFrame", "TimeFrame"],
        "predicate": {"name": "Member", "domain": ["Object", "EventFrame", "TimeFrame"], "range": "Bool"},
        "frame": {"policy": "per_event_and_time", "event": {"variable": "event", "sort": "EventFrame"},
            "time": {"variable": "time", "sort": "TimeFrame", "semantics": "arbitrary_index_without_order"}},
        "membership": {"symbol": "Member", "argument_roles": ["object", "event", "time"]},
        "distinctness": "builtin_object_identity", "maximum": 3,
        "object_variables": ["x0", "x1", "x2", "x3"]}
    return content, context


@pytest.fixture(scope="module")
def counted_prefix_packet():
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    content, context = _counted_prefix_documents()
    codec = counted.build_counted_frame_token_codec_v1()
    codec_sha = counted.counted_frame_token_codec_sha256(codec)
    content_raw, context_raw = _counted_prefix_wire(content), _counted_prefix_wire(context)
    pieces = JSON_TOKEN.findall(content_raw.decode("utf-8"))
    positions = {piece: index for index, piece in enumerate(codec["vocabulary"])}
    ids = [1, *(positions[piece] for piece in pieces), 2]
    assert "".join(pieces).encode("utf-8") == content_raw
    assert len(content_raw) == 772 and len(pieces) == 291 and len(ids) == 293
    assert len(codec["vocabulary"]) == 28
    assert codec_sha == "8a1e8e0f8c6c2259b7c1040d3518974b1c84ac6d532521199f46a76b7d78dcd8"
    return dict(content=content, context=context, content_raw=content_raw,
        context_raw=context_raw, codec=codec, codec_sha=codec_sha, ids=ids,
        content_sha=_counted_prefix_sha(content_raw), context_sha=_counted_prefix_sha(context_raw),
        sequence_sha=_counted_prefix_sha(_counted_prefix_wire(ids)))


def _counted_prefix_call(packet, prefix, **changes):
    options = dict(expected_context_sha256=packet["context_sha"],
        codec=deepcopy(packet["codec"]), expected_codec_sha256=packet["codec_sha"])
    context_raw = changes.pop("context_raw", packet["context_raw"])
    options.update(changes)
    return compatibility.inspect_counted_content_prefix_v1(prefix, context_raw, **options)


def _counted_prefix_assert_scope(report, packet, offered):
    assert set(report) == _COUNTED_PREFIX_FIELDS
    assert report["schema"] == _COUNTED_PREFIX_SCHEMA and report["profile"] == _COUNTED_PREFIX_PROFILE
    assert report["offered_ids"] == offered
    assert report["max_sequence_tokens"] == 512 and report["remaining_token_slots"] == 512 - len(offered)
    assert report["canonical_sequence_token_count"] == 293
    assert report["canonical_sequence_sha256"] == packet["sequence_sha"]
    assert report["content_sha256"] == packet["content_sha"]
    assert report["context_sha256"] == packet["context_sha"]
    assert report["codec_sha256"] == packet["codec_sha"]
    assert report["profile_is_singleton"] is True
    assert type(report["admissible_content_count"]) is int and report["admissible_content_count"] == 1
    assert report["source_dependence_established"] is False
    assert report["context_origin"] == "target_derived_authored_declaration"
    for key in ("permitted_inference_context_verified", "numerical_runtime_available", "checkpoint_compatibility_verified"):
        assert report[key] is False
    assert report["authority"] and all(type(value) is bool and value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["producer_pins"] and report["limitations"]


def test_counted_prefix_all_294_states_exhaust_singleton_without_source_or_score_inputs(counted_prefix_packet):
    packet = counted_prefix_packet
    for length in range(294):
        offered = packet["ids"][:length]
        report = _counted_prefix_call(packet, offered)
        _counted_prefix_assert_scope(report, packet, offered)
        assert report["context_raw_sha256"] == packet["context_sha"]
        assert report["matched_prefix_length"] == length
        assert report["completion_tokens_remaining"] == 293 - length
        assert report["reason"] is None
        if length < 293:
            assert report["status"] == "prefix"
            assert report["allowed_token_ids"] == [packet["ids"][length]]
            assert report["complete_candidate"] is None
        else:
            assert report["status"] == "complete" and report["allowed_token_ids"] == []
            assert report["complete_candidate"]["status"] == "valid_candidate"
            assert report["complete_candidate"]["generated_ids"] == offered


@pytest.mark.parametrize("position", [0, 1, 20, 90, 180, 250, 291, 292])
def test_counted_prefix_wrong_in_vocabulary_token_is_dead_without_repair(counted_prefix_packet, position):
    packet = counted_prefix_packet
    offered = packet["ids"][:position + 1]
    offered[position] = 3 + ((packet["ids"][position] - 3 + 1) % 25)
    report = _counted_prefix_call(packet, offered)
    _counted_prefix_assert_scope(report, packet, offered)
    assert report["status"] == "rejected" and report["reason"] == "prefix_mismatch"
    assert report["matched_prefix_length"] == position
    assert report["allowed_token_ids"] == [] and report["completion_tokens_remaining"] is None
    assert report["complete_candidate"] is None


@pytest.mark.parametrize("damage", ["missing_bos", "pad_start", "eos_start", "interior_bos", "interior_pad",
    "premature_eos", "post_eos", "missing_eos"])
def test_counted_prefix_framing_is_observed_without_insertion_or_truncation(counted_prefix_packet, damage):
    packet = counted_prefix_packet
    ids = list(packet["ids"])
    if damage == "missing_bos": ids = ids[1:]
    elif damage == "pad_start": ids = [0]
    elif damage == "eos_start": ids = [2]
    elif damage == "interior_bos": ids = ids[:10] + [1]
    elif damage == "interior_pad": ids = ids[:10] + [0]
    elif damage == "premature_eos": ids = ids[:10] + [2]
    elif damage == "post_eos": ids += [3]
    else: ids = ids[:-1]
    report = _counted_prefix_call(packet, ids)
    _counted_prefix_assert_scope(report, packet, ids)
    if damage == "missing_eos":
        assert report["status"] == "prefix" and report["allowed_token_ids"] == [2]
        assert report["completion_tokens_remaining"] == 1
    else:
        assert report["status"] == "rejected" and report["reason"] == "prefix_mismatch"
        assert report["allowed_token_ids"] == [] and report["completion_tokens_remaining"] is None
    assert report["complete_candidate"] is None


@pytest.mark.parametrize("identifier", [-1, 28, 123456, -(1 << 62)])
def test_counted_prefix_bounded_oov_ids_are_preserved_as_rejected_evidence(counted_prefix_packet, identifier):
    offered = [1, identifier]
    report = _counted_prefix_call(counted_prefix_packet, offered)
    _counted_prefix_assert_scope(report, counted_prefix_packet, offered)
    assert report["status"] == "rejected" and report["reason"] == "out_of_vocabulary_id"
    assert report["allowed_token_ids"] == [] and report["completion_tokens_remaining"] is None
    assert report["complete_candidate"] is None


def test_counted_prefix_512_id_dead_input_is_rejection_not_live_budget_exhaustion(counted_prefix_packet):
    offered = [1] + [3] * 511
    report = _counted_prefix_call(counted_prefix_packet, offered)
    assert report["status"] == "rejected" and report["reason"] == "prefix_mismatch"
    assert report["remaining_token_slots"] == 0 and report["completion_tokens_remaining"] is None
    assert report["offered_ids"] == offered and report["allowed_token_ids"] == []


@pytest.mark.parametrize("prefix", [None, (), {}, [True], [1.0], ["1"], [1 << 63], [-(1 << 63)], [1] * 513])
def test_counted_prefix_malformed_api_ids_refuse_before_lazy_owners(counted_prefix_packet, monkeypatch, prefix):
    monkeypatch.setattr(compatibility, "_counted_prefix_owners", lambda: pytest.fail("owner loaded before ID preflight"))
    with pytest.raises(ValueError):
        _counted_prefix_call(counted_prefix_packet, prefix)


@pytest.mark.parametrize("pin", [None, "0" * 64, "A" * 64, "not-a-digest"])
def test_counted_prefix_independent_context_pin_refuses_before_lazy_owners(counted_prefix_packet, monkeypatch, pin):
    monkeypatch.setattr(compatibility, "_counted_prefix_owners", lambda: pytest.fail("owner loaded before context pin preflight"))
    with pytest.raises(ValueError):
        _counted_prefix_call(counted_prefix_packet, [1], expected_context_sha256=pin)


@pytest.mark.parametrize("damage", ["sorts", "maximum_bool", "maximum_four", "roles", "frame", "distinctness", "predicate"])
def test_counted_prefix_resealed_context_cannot_widen_the_fixed_profile(counted_prefix_packet, monkeypatch, damage):
    context = deepcopy(counted_prefix_packet["context"])
    if damage == "sorts": context["sorts"].reverse()
    elif damage == "maximum_bool": context["maximum"] = True
    elif damage == "maximum_four": context["maximum"] = 4
    elif damage == "roles": context["membership"]["argument_roles"].reverse()
    elif damage == "frame": context["frame"]["policy"] = "global_lifetime"
    elif damage == "distinctness": context["distinctness"] = "occurrence_multiplicity"
    else: context["predicate"]["domain"].reverse()
    raw = _counted_prefix_wire(context)
    monkeypatch.setattr(compatibility, "_counted_prefix_owners", lambda: pytest.fail("owner loaded for foreign fixed context"))
    with pytest.raises(ValueError):
        _counted_prefix_call(counted_prefix_packet, [1], context_raw=raw, expected_context_sha256=_counted_prefix_sha(raw))


@pytest.mark.parametrize("raw", [b"", b"{", b"[]", b'{"schema":1,"schema":2}', b'{"maximum":NaN}', b'{"schema":"\\ud800"}'])
def test_counted_prefix_malformed_context_refuses_before_lazy_owners(counted_prefix_packet, monkeypatch, raw):
    monkeypatch.setattr(compatibility, "_counted_prefix_owners", lambda: pytest.fail("owner loaded for malformed context"))
    with pytest.raises(ValueError):
        _counted_prefix_call(counted_prefix_packet, [1], context_raw=raw, expected_context_sha256=_counted_prefix_sha(raw))


def test_counted_prefix_context_raw_transport_pin_stays_distinct_from_canonical_identity(counted_prefix_packet):
    packet = counted_prefix_packet
    padded = b" \n" + packet["context_raw"] + b"\n "
    with pytest.raises(ValueError):
        _counted_prefix_call(packet, [1], context_raw=padded)
    report = _counted_prefix_call(packet, [1], context_raw=padded, expected_context_sha256=_counted_prefix_sha(padded))
    assert report["context_raw_sha256"] == _counted_prefix_sha(padded)
    assert report["context_sha256"] == packet["context_sha"] and report["status"] == "prefix"


@pytest.mark.parametrize("damage", ["schema", "vocabulary_order", "extra_token", "maximum", "compatibility_true"])
def test_counted_prefix_resealed_foreign_codec_refuses_before_lazy_owners(counted_prefix_packet, monkeypatch, damage):
    codec = deepcopy(counted_prefix_packet["codec"])
    if damage == "schema": codec["schema"] = "legal-relational-compact-token-codec/v1"
    elif damage == "vocabulary_order": codec["vocabulary"][3:5] = reversed(codec["vocabulary"][3:5])
    elif damage == "extra_token": codec["vocabulary"].append('"exists"'); codec["vocabulary_size"] += 1
    elif damage == "maximum": codec["max_sequence_tokens"] = 513
    else: codec["numerical_head_compatible"] = True
    monkeypatch.setattr(compatibility, "_counted_prefix_owners", lambda: pytest.fail("owner loaded for foreign counted codec"))
    with pytest.raises(ValueError):
        _counted_prefix_call(counted_prefix_packet, [1], codec=codec, expected_codec_sha256=_counted_prefix_sha(_counted_prefix_wire(codec)))


def test_counted_prefix_old_537_codec_remains_a_distinct_closed_contract(counted_prefix_packet, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as legacy
    codec = legacy.build_compact_content_token_codec_v1()
    monkeypatch.setattr(compatibility, "_counted_prefix_owners", lambda: pytest.fail("owner loaded for legacy537 codec"))
    with pytest.raises(ValueError):
        _counted_prefix_call(counted_prefix_packet, [1], codec=codec,
            expected_codec_sha256=legacy.compact_content_token_codec_sha256(codec))


def test_counted_prefix_complete_candidate_is_genuinely_decoded_with_exact_original_ids(counted_prefix_packet, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    actual, calls = counted.decode_counted_frame_tokens_v1, []
    def decode(ids, raw, **options):
        calls.append((list(ids), raw, deepcopy(options)))
        return actual(ids, raw, **options)
    monkeypatch.setattr(counted, "decode_counted_frame_tokens_v1", decode)
    report = _counted_prefix_call(counted_prefix_packet, list(counted_prefix_packet["ids"]))
    assert len(calls) == 1 and calls[0][0] == counted_prefix_packet["ids"]
    candidate = report["complete_candidate"]
    assert candidate["canonical_content_raw_utf8"].encode() == counted_prefix_packet["content_raw"]
    assert candidate["counts"] == {"nodes": 49, "quantifiers": 6, "membership_occurrences": 4,
        "equality_occurrences": 6, "variable_occurrences": 24}
    assert candidate["prediction"]["identity_mode"] == "generated"
    assert candidate["generated_ids"] == counted_prefix_packet["ids"]


def test_counted_prefix_live_and_dead_prefixes_do_not_claim_complete_candidate_validation(counted_prefix_packet, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    monkeypatch.setattr(counted, "decode_counted_frame_tokens_v1",
        lambda *_args, **_kwargs: pytest.fail("incomplete/dead prefix passed as complete candidate"))
    for offered in ([], [1], counted_prefix_packet["ids"][:-1], [1, 0]):
        report = _counted_prefix_call(counted_prefix_packet, offered)
        assert report["complete_candidate"] is None


def test_counted_prefix_original_inputs_and_reports_remain_detached(counted_prefix_packet):
    packet = counted_prefix_packet
    prefix, codec = [1], deepcopy(packet["codec"])
    before = deepcopy(codec)
    first = _counted_prefix_call(packet, prefix, codec=codec)
    assert prefix == [1] and codec == before
    first["offered_ids"].append(0)
    first["allowed_token_ids"].append(0)
    first["producer_pins"].clear()
    second = _counted_prefix_call(packet, prefix, codec=codec)
    assert second["offered_ids"] == [1] and len(second["allowed_token_ids"]) == 1
    assert second["producer_pins"] and codec == before


@pytest.mark.parametrize("target", ["prefix", "codec"])
def test_counted_prefix_caller_mutation_during_genuine_projection_is_refused(counted_prefix_packet, monkeypatch, target):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    packet = counted_prefix_packet
    prefix, codec = [1], deepcopy(packet["codec"])
    actual = counted.project_counted_frame_request_v1
    def project(*args, **options):
        report = actual(*args, **options)
        if target == "prefix": prefix.append(0)
        else: codec["authored_mutation_after_projection"] = True
        return report
    monkeypatch.setattr(counted, "project_counted_frame_request_v1", project)
    with pytest.raises(ValueError):
        _counted_prefix_call(packet, prefix, codec=codec)


@pytest.mark.parametrize("target", ["codec", "prefix"])
def test_counted_prefix_detached_public_producer_inputs_are_fenced(counted_prefix_packet, monkeypatch, target):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    packet = counted_prefix_packet
    prefix = list(packet["ids"]) if target == "prefix" else [1]
    codec = deepcopy(packet["codec"])
    if target == "codec":
        actual = counted.encode_counted_frame_tokens_v1
        def encode(*args, **options):
            report = actual(*args, **options)
            options["codec"]["authored_detached_mutation"] = True
            return report
        monkeypatch.setattr(counted, "encode_counted_frame_tokens_v1", encode)
    else:
        actual = counted.decode_counted_frame_tokens_v1
        def decode(ids, *args, **options):
            report = actual(ids, *args, **options)
            ids.append(0)
            return report
        monkeypatch.setattr(counted, "decode_counted_frame_tokens_v1", decode)
    with pytest.raises(ValueError):
        _counted_prefix_call(packet, prefix, codec=codec)
    assert prefix == (packet["ids"] if target == "prefix" else [1])
    assert codec == packet["codec"]


@pytest.mark.parametrize("boundary", ["preloaded", "public_projection", "final_wire"])
def test_counted_prefix_loaded_owner_origin_is_rechecked_through_final_wire(counted_prefix_packet, monkeypatch, tmp_path, boundary):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    actual_project, actual_wire = counted.project_counted_frame_request_v1, compatibility._counted_prefix_wire
    foreign = str(tmp_path / "foreign-owner.py")
    def project(*args, **options):
        report = actual_project(*args, **options)
        if boundary == "public_projection": monkeypatch.setattr(counted, "__file__", foreign)
        return report
    def wire(value, *args, **options):
        raw = actual_wire(value, *args, **options)
        if boundary == "final_wire" and type(value) is dict and value.get("schema") == _COUNTED_PREFIX_SCHEMA:
            monkeypatch.setattr(counted, "__file__", foreign)
        return raw
    monkeypatch.setattr(counted, "project_counted_frame_request_v1", project)
    monkeypatch.setattr(compatibility, "_counted_prefix_wire", wire)
    if boundary == "preloaded": monkeypatch.setattr(counted, "__file__", foreign)
    with pytest.raises(ValueError):
        _counted_prefix_call(counted_prefix_packet, [1])


@pytest.mark.parametrize("boundary", ["public_projection", "final_wire"])
def test_counted_prefix_named_source_observations_are_fenced_at_public_and_serialization_boundaries(
        counted_prefix_packet, monkeypatch, boundary):
    """Only the sampled source observation is doubled, not project/encode/decode."""
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    actual_project = counted.project_counted_frame_request_v1
    actual_source, actual_wire = compatibility._counted_prefix_source, compatibility._counted_prefix_wire
    changed = False
    def project(*args, **options):
        nonlocal changed
        report = actual_project(*args, **options)
        if boundary == "public_projection": changed = True
        return report
    def source(path, *args, **options):
        digest, witness = actual_source(path, *args, **options)
        if changed and str(path).endswith("/parsers/fol.py"):
            return "0" * 64, witness
        return digest, witness
    def wire(value, *args, **options):
        nonlocal changed
        raw = actual_wire(value, *args, **options)
        if boundary == "final_wire" and type(value) is dict and value.get("schema") == _COUNTED_PREFIX_SCHEMA:
            changed = True
        return raw
    monkeypatch.setattr(counted, "project_counted_frame_request_v1", project)
    monkeypatch.setattr(compatibility, "_counted_prefix_source", source)
    monkeypatch.setattr(compatibility, "_counted_prefix_wire", wire)
    with pytest.raises(ValueError):
        _counted_prefix_call(counted_prefix_packet, [1])


def test_counted_prefix_original_input_is_rechecked_after_final_serialization(counted_prefix_packet, monkeypatch):
    prefix = [1]
    actual = compatibility._counted_prefix_wire
    def wire(value, *args, **options):
        raw = actual(value, *args, **options)
        if type(value) is dict and value.get("schema") == _COUNTED_PREFIX_SCHEMA:
            prefix.append(0)
        return raw
    monkeypatch.setattr(compatibility, "_counted_prefix_wire", wire)
    with pytest.raises(ValueError):
        _counted_prefix_call(counted_prefix_packet, prefix)


def test_counted_prefix_signature_accepts_no_target_sidecar_logits_or_runtime_context():
    import inspect
    parameters = inspect.signature(compatibility.inspect_counted_content_prefix_v1).parameters
    assert list(parameters) == ["prefix_ids", "context_raw", "expected_context_sha256", "codec", "expected_codec_sha256"]
    assert all(parameters[key].kind == inspect.Parameter.KEYWORD_ONLY for key in
        ("expected_context_sha256", "codec", "expected_codec_sha256"))


@pytest.mark.parametrize("pin", [None, "0" * 64])
def test_counted_prefix_independent_codec_pin_refuses_before_lazy_owners(counted_prefix_packet, monkeypatch, pin):
    monkeypatch.setattr(compatibility, "_counted_prefix_owners", lambda: pytest.fail("owner loaded before codec pin preflight"))
    with pytest.raises(ValueError):
        _counted_prefix_call(counted_prefix_packet, [1], expected_codec_sha256=pin)


def test_counted_prefix_primitive_subclasses_are_not_ordinary_api_data(counted_prefix_packet, monkeypatch):
    class IdList(list):
        pass
    class Identifier(int):
        pass
    monkeypatch.setattr(compatibility, "_counted_prefix_owners", lambda: pytest.fail("owner loaded for primitive subclass"))
    for offered in (IdList([1]), [Identifier(1)]):
        with pytest.raises(ValueError):
            _counted_prefix_call(counted_prefix_packet, offered)


def test_counted_prefix_primary_interrupt_survives_a_closing_origin_refusal(counted_prefix_packet, monkeypatch, tmp_path):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    failure = KeyboardInterrupt("authored interruption at genuine producer seam")
    def interrupted(*_args, **_options):
        monkeypatch.setattr(counted, "__file__", str(tmp_path / "foreign-origin.py"))
        raise failure
    monkeypatch.setattr(counted, "project_counted_frame_request_v1", interrupted)
    with pytest.raises(KeyboardInterrupt) as caught:
        _counted_prefix_call(counted_prefix_packet, [1])
    assert caught.value is failure
    assert any("closing" in note.lower() for note in getattr(failure, "__notes__", ()))


@pytest.mark.parametrize("producer", ["projection", "encoding", "complete_candidate"])
def test_counted_prefix_changed_genuine_public_return_is_not_accepted_as_a_new_profile(
        counted_prefix_packet, monkeypatch, producer):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    packet = counted_prefix_packet
    if producer == "projection":
        actual = counted.project_counted_frame_request_v1
        def project(*args, **options):
            report = actual(*args, **options)
            report["original_expression_sha256"] = "0" * 64
            return report
        monkeypatch.setattr(counted, "project_counted_frame_request_v1", project)
    elif producer == "encoding":
        actual = counted.encode_counted_frame_tokens_v1
        def encode(*args, **options):
            report = actual(*args, **options)
            report["target_ids"].pop()
            return report
        monkeypatch.setattr(counted, "encode_counted_frame_tokens_v1", encode)
    else:
        actual = counted.decode_counted_frame_tokens_v1
        def decode(*args, **options):
            report = actual(*args, **options)
            report["generated_ids"].pop()
            return report
        monkeypatch.setattr(counted, "decode_counted_frame_tokens_v1", decode)
    with pytest.raises(ValueError):
        _counted_prefix_call(packet, list(packet["ids"]) if producer == "complete_candidate" else [1])


# Explicit source/head conditioning metadata; these are authored declarations.
# No test below authenticates a native producer, loads a model, or admits law.
_NATIVE_HEAD_CONTRACT_SCHEMA = "legal-conditioning-space-contract/v1"
_NATIVE_HEAD_INSPECTION_SCHEMA = "legal-source-head-conditioning-inspection/v1"


def _native_head_contract(*, dimension=384, boundary="decoder_input"):
    return {
        "schema": _NATIVE_HEAD_CONTRACT_SCHEMA,
        "artifact_sha256": hashlib.sha256(b"authored source declaration fixture").hexdigest(),
        "boundary": boundary,
        "dimension": dimension,
        "producer": {"schema": "authored-gte-producer-metadata/v1",
            "model": "thenlper/gte-small", "revision": "17e1f347d17fe144873b1201da91788898c639cd",
            "pooling": "mean", "normalization": "l2",
            "tokenizer": {"schema": "authored-tokenizer-policy/v1", "untruncated": True,
                          "maximum_tokens_including_special": 512}},
        "preprocessing": {"schema": "authored-source-preprocessing/v1",
            "normalization": "none", "source_bytes": "exact_utf8", "overlength": "reject"},
        "ordered_transforms": [],
        "basis": {"schema": "authored-coordinate-basis/v1", "kind": "raw_native_model_coordinates",
                  "coordinate_order": "model_output_order"},
        "required_side_inputs": [],
    }


def _native_head_raw(value):
    return canonical(value, ascii=False).encode("utf-8")


def _native_head_inspect(source=None, head=None, **changes):
    source = _native_head_contract() if source is None else source
    head = deepcopy(source) if head is None else head
    source_raw, head_raw = _native_head_raw(source), _native_head_raw(head)
    options = dict(expected_source_contract_sha256=hashlib.sha256(source_raw).hexdigest(),
                   expected_head_contract_sha256=hashlib.sha256(head_raw).hexdigest())
    options.update(changes)
    return compatibility.inspect_source_head_conditioning_v1(source_raw, head_raw, **options)


def _native_head_assert_unqualified(report):
    assert report["schema"] == _NATIVE_HEAD_INSPECTION_SCHEMA
    assert report["comparison_scope"] == "caller_declared_conditioning_component_only"
    assert report["full_decoder_input_verified"] is False
    assert report["execution_ready"] is False
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["model_calls"]) is int and report["model_calls"] == 0
    assert type(report["training_calls"]) is int and report["training_calls"] == 0


def test_native_head_full_declared_match_retains_artifacts_without_granting_compatibility():
    source = _native_head_contract()
    head = deepcopy(source)
    head["artifact_sha256"] = hashlib.sha256(b"different authored head declaration fixture").hexdigest()
    report = _native_head_inspect(source, head)
    assert report["relation"] == "matching"
    assert report["disposition"] == "declared_contract_match"
    assert report["mismatched_components"] == report["unresolved_components"] == []
    assert report["source_artifact_sha256"] == source["artifact_sha256"]
    assert report["head_artifact_sha256"] == head["artifact_sha256"]
    assert report["source_artifact_sha256"] != report["head_artifact_sha256"]
    assert report["component_sha256"]["source"] == report["component_sha256"]["head"]
    _native_head_assert_unqualified(report)


@pytest.mark.parametrize("component", ["dimension", "producer", "preprocessing", "ordered_transforms", "basis"])
def test_native_head_full_component_difference_cannot_hide_behind_equal_width_labels(component):
    source = _native_head_contract()
    head = deepcopy(source)
    if component == "dimension":
        head[component] = 768
    elif component == "ordered_transforms":
        head[component] = [{"schema": "authored-center-rms/v1", "mean_sha256": "1" * 64, "scale": 0.25}]
    elif component == "producer":
        head[component]["tokenizer"]["untruncated"] = False
    elif component == "preprocessing":
        head[component]["normalization"] = "collapse_whitespace_then_strip"
    else:
        head[component]["kind"] = "authored_sparse_coordinates"
    report = _native_head_inspect(source, head)
    assert report["relation"] == "different"
    assert report["disposition"] == "refused_contract_mismatch"
    assert report["mismatched_components"] == [component]
    assert report["unresolved_components"] == []
    _native_head_assert_unqualified(report)


@pytest.mark.parametrize("component", ["producer", "preprocessing", "ordered_transforms", "basis"])
def test_native_head_missing_training_lineage_is_unknown_even_when_both_declarations_omit_it(component):
    source = _native_head_contract()
    source[component] = None
    report = _native_head_inspect(source)
    assert report["relation"] == "unknown"
    assert report["disposition"] == "conditioning_contract_unresolved"
    assert report["unresolved_components"] == [component]
    assert report["mismatched_components"] == []
    _native_head_assert_unqualified(report)


def test_native_head_known_mismatch_survives_another_unresolved_component():
    source = _native_head_contract()
    head = deepcopy(source)
    source["producer"] = None
    head["basis"]["kind"] = "authored_sparse_coordinates"
    report = _native_head_inspect(source, head)
    assert report["relation"] == "different"
    assert report["mismatched_components"] == ["basis"]
    assert report["unresolved_components"] == ["producer"]
    _native_head_assert_unqualified(report)


def test_native_head_fitted_transform_sequence_preserves_order_and_complete_parameters():
    source = _native_head_contract()
    source["ordered_transforms"] = [
        {"schema": "authored-center/v1", "mean_sha256": "1" * 64},
        {"schema": "authored-rms/v1", "scale": 0.25, "statistics_origin": "training_only"},
    ]
    head = deepcopy(source)
    head["ordered_transforms"].reverse()
    report = _native_head_inspect(source, head)
    assert report["relation"] == "different"
    assert report["mismatched_components"] == ["ordered_transforms"]
    _native_head_assert_unqualified(report)


def test_native_head_source_clause_and_padding_requirements_are_retained_unsatisfied():
    source = _native_head_contract()
    head = deepcopy(source)
    head["required_side_inputs"] = [
        {"schema": "authored-clause-source-context/v1", "representation": "transformed_clause_vectors",
         "availability": "unprovided"},
        {"schema": "authored-source-padding-mask/v1", "availability": "unprovided"},
    ]
    report = _native_head_inspect(source, head)
    assert report["relation"] == "matching"
    assert report["required_side_inputs"] == {"source": [], "head": head["required_side_inputs"]}
    _native_head_assert_unqualified(report)


def test_native_head_encoder_output_needs_adapter_before_decoder_input_even_at_equal_width():
    source = _native_head_contract(boundary="encoder_output")
    head = _native_head_contract()
    head["basis"] = None
    head["ordered_transforms"] = [{"schema": "authored-center-rms/v1", "scale": 0.25}]
    report = _native_head_inspect(source, head)
    assert report["relation"] == "adapter_required"
    assert report["disposition"] == "adapter_required"
    assert report["source_boundary"] == "encoder_output" and report["head_boundary"] == "decoder_input"
    assert report["unresolved_components"] == ["basis"]
    assert report["mismatched_components"] == ["ordered_transforms"]
    _native_head_assert_unqualified(report)


def test_native_head_spacy_eight_features_and_learned_eight_formula_basis_stay_distinct():
    source = _native_head_contract(dimension=8)
    source["producer"] = {"schema": "authored-spacy-features/v1", "model": "en_core_web_sm",
                          "model_version": "3.8.0", "feature_count": 8}
    source["basis"] = {"schema": "authored-spacy-feature-order/v1", "meaning": "linguistic_features"}
    head = deepcopy(source)
    head["producer"] = {"schema": "authored-external-formula-donor/v1", "training_inputs": "synthetic"}
    head["basis"] = {"schema": "authored-eight-formula-basis/v1", "meaning": "external_unverified_vectors"}
    report = _native_head_inspect(source, head)
    assert report["source_dimension"] == report["head_dimension"] == 8
    assert report["mismatched_components"] == ["producer", "basis"]
    assert report["relation"] == "different"
    _native_head_assert_unqualified(report)


def test_native_head_native_768_uses_its_own_cls_producer_descriptor():
    source = _native_head_contract(dimension=768)
    source["producer"] = {"schema": "authored-gte-multilingual-producer/v1",
        "model": "Alibaba-NLP/gte-multilingual-base", "revision": "9bbca17d9273fd0d03d5725c7a4b0f6b45142062",
        "code_revision": "40ced75c3017eb27626c9d4ea981bde21a2662f4", "pooling": "cls", "normalization": "l2"}
    report = _native_head_inspect(source)
    assert report["relation"] == "matching"
    assert report["source_dimension"] == report["head_dimension"] == 768
    _native_head_assert_unqualified(report)


def test_native_head_leanstral_4096_match_does_not_satisfy_required_raw_text():
    source = _native_head_contract(dimension=4096)
    source["producer"] = {"schema": "authored-leanstral-full-forward-producer/v1",
        "model_sha256": "4668fd2a6d2764de250489852230e96238eb5c0d7495866eb3b9c6c4fac5c7da",
        "profile": "leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2",
        "pooling": "last", "normalization": "l2"}
    head = deepcopy(source)
    head["required_side_inputs"] = [{"schema": "authored-bound-span-source-text/v1", "required": True}]
    report = _native_head_inspect(source, head)
    assert report["relation"] == "matching"
    assert report["required_side_inputs"]["head"] == head["required_side_inputs"]
    _native_head_assert_unqualified(report)


@pytest.mark.parametrize("field", ["expected_source_contract_sha256", "expected_head_contract_sha256"])
def test_native_head_independent_raw_document_pin_must_match(field):
    with pytest.raises(ValueError):
        _native_head_inspect(**{field: "0" * 64})


def test_native_head_duplicate_json_keys_refuse_even_with_matching_raw_pin():
    raw = _native_head_raw(_native_head_contract())
    bad = b'{"dimension":384,' + raw[1:]
    with pytest.raises(ValueError):
        compatibility.inspect_source_head_conditioning_v1(bad, raw,
            expected_source_contract_sha256=hashlib.sha256(bad).hexdigest(),
            expected_head_contract_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("constant", [b"NaN"])
def test_native_head_nonfinite_nested_metadata_refuses(constant):
    raw = _native_head_raw(_native_head_contract())
    bad = raw.replace(b'"producer":{', b'"producer":{"nonfinite":' + constant + b',', 1)
    assert bad != raw
    with pytest.raises(ValueError):
        compatibility.inspect_source_head_conditioning_v1(bad, raw,
            expected_source_contract_sha256=hashlib.sha256(bad).hexdigest(),
            expected_head_contract_sha256=hashlib.sha256(raw).hexdigest())


def test_native_head_head_contract_cannot_describe_an_encoder_output():
    head = _native_head_contract(boundary="encoder_output")
    with pytest.raises(ValueError):
        _native_head_inspect(_native_head_contract(), head)


@pytest.mark.parametrize("dimension", [True])
def test_native_head_dimension_requires_supported_plain_integer(dimension):
    source = _native_head_contract()
    source["dimension"] = dimension
    with pytest.raises(ValueError):
        _native_head_inspect(source)


def test_native_head_unknown_top_level_field_does_not_become_hidden_runtime_input():
    source = _native_head_contract()
    source["target_ast"] = {"schema": "authored-target/v1"}
    with pytest.raises(ValueError):
        _native_head_inspect(source)


def test_native_head_raw_document_requires_plain_bytes_without_callbacks():
    class CallbackBytes(bytes):
        def decode(self, *_args, **_kwargs):
            pytest.fail("custom document decode callback executed")
    raw = _native_head_raw(_native_head_contract())
    with pytest.raises(ValueError):
        compatibility.inspect_source_head_conditioning_v1(CallbackBytes(raw), raw,
            expected_source_contract_sha256=hashlib.sha256(raw).hexdigest(),
            expected_head_contract_sha256=hashlib.sha256(raw).hexdigest())


def test_native_head_metadata_depth_is_bounded_before_component_comparison():
    source = _native_head_contract()
    nested = {"schema": "authored-deep-metadata/v1"}
    source["producer"]["extra_recipe"] = nested
    for _ in range(40):
        child = {"schema": "authored-deep-metadata/v1"}
        nested["child"] = child
        nested = child
    with pytest.raises(ValueError):
        _native_head_inspect(source)


def test_native_head_metadata_inspection_opens_no_existing_model_or_source_owner(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("pure conditioning assessment opened a runtime dependency")
    monkeypatch.setattr(compatibility, "_compact_role_owners", forbidden)
    monkeypatch.setattr(compatibility, "_counted_prefix_owners", forbidden)
    report = _native_head_inspect()
    assert report["relation"] == "matching"
    _native_head_assert_unqualified(report)


def test_native_head_raw_whitespace_identity_is_separate_from_complete_component_identity():
    source = _native_head_contract()
    compact = _native_head_raw(source)
    pretty = json.dumps(source, indent=2, ensure_ascii=False).encode("utf-8")
    assert pretty != compact
    report = compatibility.inspect_source_head_conditioning_v1(pretty, compact,
        expected_source_contract_sha256=hashlib.sha256(pretty).hexdigest(),
        expected_head_contract_sha256=hashlib.sha256(compact).hexdigest())
    assert report["source_contract_sha256"] != report["head_contract_sha256"]
    assert report["relation"] == "matching"
    _native_head_assert_unqualified(report)


@pytest.mark.parametrize("head_value", [1.0, True])
def test_native_head_component_comparison_preserves_numeric_and_boolean_types(head_value):
    source = _native_head_contract()
    source["producer"]["recipe_numeric"] = 1
    head = deepcopy(source)
    head["producer"]["recipe_numeric"] = head_value
    assert source["producer"]["recipe_numeric"] == head_value
    report = _native_head_inspect(source, head)
    assert report["relation"] == "different"
    assert report["mismatched_components"] == ["producer"]
    _native_head_assert_unqualified(report)


# Raw checkpoint/TRAIN provenance controls. All authored fixtures below use the
# unchanged original metadata validators, never a model or fabricated validator.
_CHECKPOINT_CONDITIONING_SCHEMA = "legal-normative-checkpoint-conditioning-inspection/v1"


def _checkpoint_conditioning_reseal(value):
    value.pop("receipt_sha256", None)
    value["receipt_sha256"] = bound_contextual._digest(value)
    return value


def _checkpoint_conditioning_fixture(tmp_path, dimension=384, recipe="normative-wording-ce", *, distinct=False):
    data = bound_original_fixture.make_normative(tmp_path, dimension, recipe)
    checkpoint, preprocessing = data["checkpoint"], data["preprocessing"]
    train, validation = [deepcopy(data["rows"][0])], [deepcopy(data["rows"][1])]
    contexts = {"train": {train[0]["id"]: deepcopy(data["contexts"][train[0]["id"]])},
                "validation": {validation[0]["id"]: deepcopy(data["contexts"][validation[0]["id"]])}}
    clauses = bound_cached_fixture.bounded.clauses
    binding = clauses.validate_training_contexts(train, validation, contexts)
    cache = {}
    for split, rows in (("train", train), ("validation", validation)):
        cache[split] = [{"id": "clause:" + contexts[split][rows[0]["id"]]["source_sha256"],
            "source_text": rows[0]["source_text"], "input": deepcopy(rows[0]["input"])}]
    if dimension == 384:
        representation = dict(kind="native_gte_small_semantic_embedding", dimension=384,
            producer_schema="preserved_original_clause_context_inputs", profile_id=None,
            profile_evidence_scope="caller-authenticated original384 artifact closure; no encoder re-execution",
            context_binding_sha256=bound_contextual._digest(binding),
            semantic_embedding=True, paragraph_and_clause_views_preserved=True)
    else:
        representation = dict(kind="native_gte_multilingual_semantic_embedding", dimension=768,
            producer_schema="bounded-native768-source-production/v1",
            profile_id=bound_cached_fixture.complete.PROFILE_ID, semantic_embedding=True,
            historical_profile_token_limit=8192, experiment_admission_token_limit=512,
            cached_profile_relabelled=False)
    lane = dict(train=train, validation=validation, clause_cache=cache,
        source_contexts=contexts, context_binding=binding, representation=representation)
    bundle = dict(schema="matched-dimension-source-inputs/v1", complete=True,
        plan_sha256="c" * 64, dimensions={str(dimension): lane},
        historical8_production_sha256="d" * 64, bounded768_production_sha256="e" * 64,
        native768_cached_report={"path": "/authored-unopened-native-report.json", "bytes": 1, "sha256": "f" * 64},
        source_aliases=[], representation_kinds={"8": "historical_linguistic_feature_hash",
            "384": "native_gte_small_semantic_embedding", "768": "native_gte_multilingual_semantic_embedding"},
        original384_paragraph_and_clause_views_preserved=True, targets_attached=False,
        **bound_cached_fixture.bounded.FALSE)
    bundle["inputs_sha256"] = bound_contextual._digest(bundle)
    preprocessing["source_binding"] = deepcopy(binding)
    preprocessing["representation"] = deepcopy(representation)
    lineage = bound_contextual._digest(lane)
    checkpoint["lineage"]["input_provenance_sha256"] = preprocessing["source_inputs_sha256"] = lineage
    paragraph = deepcopy(preprocessing["paragraph_normalization"])
    paragraph.update(expected_training_ids=[row["id"] for row in train],
        forbidden_validation_ids=[row["id"] for row in validation])
    clause = deepcopy(preprocessing["clause_normalization"])
    clause.update(expected_training_ids=[row["id"] for row in binding["training_clause_inventory"]],
        forbidden_validation_ids=[row["id"] for row in binding["validation_clause_inventory"]],
        training_contexts_sha256=bound_contextual._digest(contexts["train"]))
    if distinct:
        paragraph.update(mean=[1.0] * dimension, fitted_training_mean=[1.0] * dimension,
                         scale=2.0, fitted_training_scale=2.0)
        clause.update(mean=[2.0] * dimension, fitted_training_mean=[2.0] * dimension,
                      scale=4.0, fitted_training_scale=4.0)
    paragraph, clause = _checkpoint_conditioning_reseal(paragraph), _checkpoint_conditioning_reseal(clause)
    preprocessing["paragraph_normalization"], preprocessing["clause_normalization"] = paragraph, clause
    checkpoint["architecture"]["normalization"] = deepcopy(paragraph)
    checkpoint["architecture"]["clause_normalization"] = deepcopy(clause)
    checkpoint["model_state"].update({"body.source_mean": deepcopy(paragraph["mean"]),
        "body.source_scale": paragraph["scale"], "clause_source_mean": deepcopy(clause["mean"]),
        "clause_source_scale": clause["scale"]})
    checkpoint["weights_sha256"] = bound_contextual._digest(checkpoint["model_state"])
    checkpoint["tensor_sha256"] = bound_contextual._tensor_digest(checkpoint["model_state"],
        bound_contextual._shapes(dimension)[0], integer_buffers=True)
    return dict(checkpoint=checkpoint, preprocessing=preprocessing, donor=data["donor"],
                training_inputs=bundle, lane=lane, dimension=dimension, recipe=recipe)


def _checkpoint_conditioning_raw(value):
    return canonical(value, ascii=False).encode("utf-8")


def _checkpoint_conditioning_call(packet, *, training=True, **changes):
    raws = {key: _checkpoint_conditioning_raw(packet[key])
            for key in ("checkpoint", "preprocessing", "donor", "training_inputs")}
    options = {"expected_" + key + "_sha256": hashlib.sha256(raws[key]).hexdigest()
               for key in ("checkpoint", "preprocessing", "donor")}
    options.update(expected_training_inputs_sha256=hashlib.sha256(raws["training_inputs"]).hexdigest()
                   if training else None, training_recipe_name=packet["recipe"])
    options.update(changes)
    return compatibility.inspect_normative_checkpoint_conditioning_v1(raws["checkpoint"],
        raws["preprocessing"], raws["donor"], raws["training_inputs"] if training else None, **options)


def _checkpoint_conditioning_assert_unqualified(report):
    assert report["schema"] == _CHECKPOINT_CONDITIONING_SCHEMA
    assert report["checkpoint_documents_validated"] is True
    assert report["execution_ready"] is report["full_decoder_input_verified"] is False
    assert report["authority"] and all(value is False for value in report["authority"].values())
    for field in ("training_mask", "evaluation_gold_mask", "model_calls", "training_calls"):
        assert type(report[field]) is int and report[field] == 0
    assert report["head_contract"]["boundary"] == "decoder_input"
    assert report["head_contract_sha256"] == hashlib.sha256(
        _checkpoint_conditioning_raw(report["head_contract"])).hexdigest()


@pytest.mark.parametrize("dimension,recipe", [
    (384, "normative-wording-zero"), (384, "normative-wording-ce"),
    (768, "normative-wording-zero"), (768, "normative-wording-ce"),
], ids=["384-zero", "384-ce", "768-zero", "768-ce"])
def test_checkpoint_conditioning_genuine_documents_bind_selected_training_lane(tmp_path, monkeypatch, dimension, recipe):
    packet = _checkpoint_conditioning_fixture(tmp_path, dimension, recipe)
    def forbidden(*_args, **_kwargs):
        pytest.fail("raw checkpoint binding attempted a runtime or model operation")
    monkeypatch.setattr(bound_contextual, "_numeric_owner", forbidden)
    monkeypatch.setattr(compatibility, "_prepare_normative_target_binding", forbidden)
    monkeypatch.setattr(bound_contextual, "_read", forbidden)
    report = _checkpoint_conditioning_call(packet)
    assert report["dimension"] == dimension and report["training_recipe_name"] == recipe
    assert report["original_training_provenance_bound"] is True
    assert report["original_training_provenance_sha256"] == bound_contextual._digest(packet["lane"])
    assert report["training_representation"] == packet["lane"]["representation"]
    assert report["training_counts"] == {"train": 1, "validation": 1}
    assert report["training_artifact_parsed"] is True and report["source_only_training_rows_checked"] is True
    raw_training = _checkpoint_conditioning_raw(packet["training_inputs"])
    assert report["artifact_raw_sha256"]["training_inputs"] == hashlib.sha256(raw_training).hexdigest()
    assert report["artifact_raw_sha256"]["training_inputs"] != report["original_training_provenance_sha256"]
    if dimension == 384:
        assert report["head_contract"]["producer"] is report["head_contract"]["basis"] is None
        assert "recorded_training_profile_unprovided" in report["unresolved"]
    else:
        assert report["head_contract"]["producer"]["representation"] == packet["lane"]["representation"]
        assert report["head_contract"]["basis"]["profile_id"] == packet["lane"]["representation"]["profile_id"]
    _checkpoint_conditioning_assert_unqualified(report)


def test_checkpoint_conditioning_missing_training_body_preserves_unprovided_basis(tmp_path):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    report = _checkpoint_conditioning_call(packet, training=False)
    assert report["original_training_provenance_bound"] is False
    assert report["training_representation"] is report["training_counts"] is None
    assert report["artifact_raw_sha256"]["training_inputs"] is None
    assert report["head_contract"]["producer"] is report["head_contract"]["basis"] is None
    assert "original_training_inputs_unprovided" in report["unresolved"]
    _checkpoint_conditioning_assert_unqualified(report)


@pytest.mark.parametrize("artifact", ["checkpoint", "preprocessing", "donor", "training_inputs"])
def test_checkpoint_conditioning_independent_original_raw_pins_cannot_be_reassigned(tmp_path, artifact):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    with pytest.raises(ValueError):
        _checkpoint_conditioning_call(packet, **{"expected_" + artifact + "_sha256": "0" * 64})


def test_checkpoint_conditioning_new_inference_manifest_cannot_replace_original_training_lineage(tmp_path):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    packet["lane"]["representation"]["profile_evidence_scope"] = "different unreviewed source population"
    bundle = packet["training_inputs"]
    bundle["inputs_sha256"] = bound_contextual._digest({k: v for k, v in bundle.items() if k != "inputs_sha256"})
    with pytest.raises(ValueError):
        _checkpoint_conditioning_call(packet)


def test_checkpoint_conditioning_full_training_root_seal_is_independent_of_selected_lane(tmp_path):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    packet["training_inputs"]["plan_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        _checkpoint_conditioning_call(packet)


@pytest.mark.parametrize("join", ["ordered_ids", "training_contexts"])
def test_checkpoint_conditioning_real_training_id_and_context_joins_are_required(tmp_path, join):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    pp, cp = packet["preprocessing"], packet["checkpoint"]
    if join == "ordered_ids":
        pp["paragraph_normalization"]["expected_training_ids"] = ["different-training-occurrence"]
        _checkpoint_conditioning_reseal(pp["paragraph_normalization"])
        cp["architecture"]["normalization"] = deepcopy(pp["paragraph_normalization"])
    else:
        pp["clause_normalization"]["training_contexts_sha256"] = "0" * 64
        _checkpoint_conditioning_reseal(pp["clause_normalization"])
        cp["architecture"]["clause_normalization"] = deepcopy(pp["clause_normalization"])
    with pytest.raises(ValueError):
        _checkpoint_conditioning_call(packet)


def test_checkpoint_conditioning_paragraph_and_clause_normalizations_remain_separate(tmp_path):
    packet = _checkpoint_conditioning_fixture(tmp_path, distinct=True)
    report = _checkpoint_conditioning_call(packet)
    head = report["head_contract"]
    assert head["ordered_transforms"][0]["recipe"] == packet["checkpoint"]["input_transform"]
    assert head["ordered_transforms"][1]["recipe"] == packet["preprocessing"]["paragraph_normalization"]
    side = head["required_side_inputs"][0]
    assert side["ordered_transforms"][0]["recipe"] == packet["checkpoint"]["input_transform"]
    assert side["ordered_transforms"][1] == {"schema": "zero-pad-clause-context/v1", "slots": 8}
    assert side["ordered_transforms"][2]["recipe"] == packet["preprocessing"]["clause_normalization"]
    assert side["ordered_transforms"][2]["recipe"] != head["ordered_transforms"][1]["recipe"]
    assert side["padding_mask"] == "source_derived_contiguous_nonempty_bool8"
    _checkpoint_conditioning_assert_unqualified(report)


@pytest.mark.parametrize("target", ["checkpoint", "preprocessing"])
def test_checkpoint_conditioning_last_training_validator_cannot_change_original_parsed_documents(
        tmp_path, monkeypatch, target):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    actual_documents, actual_sources = bound_contextual._documents, bound_contextual._source_rows
    held, calls = [], []
    def documents(*args, **kwargs):
        result = actual_documents(*args, **kwargs)
        held.append(result)
        return result
    def sources(*args, **kwargs):
        result = actual_sources(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            held[0][target]["input_transform"]["scale"] = 8.0
        return result
    monkeypatch.setattr(bound_contextual, "_documents", documents)
    monkeypatch.setattr(bound_contextual, "_source_rows", sources)
    with pytest.raises(ValueError):
        _checkpoint_conditioning_call(packet)
    assert len(held) == 1 and len(calls) == 2


def test_checkpoint_conditioning_detached_validator_return_is_held_through_last_training_callback(
        tmp_path, monkeypatch):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    actual_documents, actual_sources = bound_contextual._documents, bound_contextual._source_rows
    held, calls = [], []
    def documents(*args, **kwargs):
        result = deepcopy(actual_documents(*args, **kwargs))
        held.append(result)
        return result
    def sources(*args, **kwargs):
        result = actual_sources(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            held[0]["donor_checkpoint"]["codec"]["schema"] = "changed-after-validation"
        return result
    monkeypatch.setattr(bound_contextual, "_documents", documents)
    monkeypatch.setattr(bound_contextual, "_source_rows", sources)
    with pytest.raises(ValueError):
        _checkpoint_conditioning_call(packet)
    assert len(held) == 1 and len(calls) == 2


def test_checkpoint_conditioning_raw_artifacts_refuse_bytes_subclass_callbacks(tmp_path):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    class ForeignBytes(bytes):
        def decode(self, *_args, **_kwargs):
            pytest.fail("foreign raw artifact decode callback executed")
    raws = {k: _checkpoint_conditioning_raw(packet[k])
            for k in ("checkpoint", "preprocessing", "donor", "training_inputs")}
    with pytest.raises(ValueError):
        compatibility.inspect_normative_checkpoint_conditioning_v1(ForeignBytes(raws["checkpoint"]),
            raws["preprocessing"], raws["donor"], raws["training_inputs"],
            **{"expected_" + k + "_sha256": hashlib.sha256(raw).hexdigest() for k, raw in raws.items()},
            training_recipe_name=packet["recipe"])


def test_checkpoint_conditioning_joint_recipe_map_change_cannot_relabel_original_profile(tmp_path, monkeypatch):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    changed = deepcopy(bound_original._RECIPES)
    changed["normative-wording-ce"]["weight"] = 0.2
    packet["checkpoint"]["recipe"] = deepcopy(changed["normative-wording-ce"])
    monkeypatch.setattr(bound_original, "_RECIPES", changed)
    with pytest.raises(ValueError):
        _checkpoint_conditioning_call(packet)


def test_checkpoint_conditioning_original_donor_raw_identity_is_not_only_canonical_tensor_equality(tmp_path):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    raws = {k: _checkpoint_conditioning_raw(packet[k])
            for k in ("checkpoint", "preprocessing", "donor", "training_inputs")}
    # Identical parsed donor metadata and tensors, but a different raw artifact.
    raws["donor"] += b"\n"
    assert json.loads(raws["donor"]) == packet["donor"]
    with pytest.raises(ValueError):
        compatibility.inspect_normative_checkpoint_conditioning_v1(raws["checkpoint"], raws["preprocessing"],
            raws["donor"], raws["training_inputs"],
            **{"expected_" + k + "_sha256": hashlib.sha256(raw).hexdigest() for k, raw in raws.items()},
            training_recipe_name=packet["recipe"])


def test_checkpoint_conditioning_joint_alternate_codec_cannot_relabel_fixed_normative_language(tmp_path, monkeypatch):
    packet = _checkpoint_conditioning_fixture(tmp_path)
    codec = packet["checkpoint"]["codec"]
    codec["target_vocabulary"][8] = '\"different_action\"'
    packet["donor"]["codec"] = deepcopy(codec)
    packet["checkpoint"]["architecture"]["codec_sha256"] = bound_contextual._digest(codec)
    packet["checkpoint"]["lineage"]["teacher_codec_sha256"] = bound_contextual._digest(codec)
    packet["checkpoint"]["lineage"]["teacher_checkpoint_sha256"] = hashlib.sha256(
        _checkpoint_conditioning_raw(packet["donor"])).hexdigest()
    actual, passed = bound_contextual._documents, []
    def documents(*args, **kwargs):
        result = actual(*args, **kwargs)
        passed.append(True)
        return result
    monkeypatch.setattr(bound_contextual, "_documents", documents)
    with pytest.raises(ValueError, match="normative32"):
        _checkpoint_conditioning_call(packet)
    assert passed == [True]


@pytest.fixture(scope="module")
def _checkpoint_conditioning_retained_inputs():
    import os
    import stat
    manifest_path = os.environ.get("LEGAL_IR_CHECKPOINT_BINDING_DATA_MANIFEST")
    expected = os.environ.get("LEGAL_IR_CHECKPOINT_BINDING_DATA_SHA256")
    exports_path = os.environ.get("LEGAL_IR_CHECKPOINT_BINDING_EXPORTS")
    if manifest_path is None and expected is None and exports_path is None:
        pytest.skip("explicit retained artifact metadata cohort was not selected")
    assert all(type(v) is str and v for v in (manifest_path, expected, exports_path))
    def read(path, maximum):
        path = Path(path)
        assert path.is_absolute() and path.resolve(strict=True) == path
        assert all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            before = os.fstat(stream.fileno())
            assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= maximum
            raw, after = stream.read(before.st_size + 1), os.fstat(stream.fileno())
        witness = lambda v: (v.st_dev, v.st_ino, v.st_mode, v.st_nlink, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
        assert len(raw) == before.st_size and witness(before) == witness(after) == witness(path.lstat())
        return raw, witness(before)
    manifest_raw, manifest_witness = read(manifest_path, 131072)
    assert hashlib.sha256(manifest_raw).hexdigest() == expected
    def pairs(items):
        result = {}
        for key, value in items:
            assert key not in result
            result[key] = value
        return result
    manifest = json.loads(manifest_raw, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    assert type(manifest) is dict and set(manifest) == {"schema", "artifacts", "cases"}
    assert manifest["schema"] == "legal-normative-checkpoint-conditioning-retained-data/v1"
    artifacts, cases = manifest["artifacts"], manifest["cases"]
    assert type(artifacts) is dict and 1 <= len(artifacts) <= 16
    assert type(cases) is list and len(cases) == 4
    expected_ids = {f"{width}-normative-wording-{recipe}" for width in (384, 768) for recipe in ("zero", "ce")}
    assert {row["id"] for row in cases} == expected_ids
    used = set()
    for row in cases:
        assert type(row) is dict and set(row) == {"id", "dimension", "training_recipe_name", "checkpoint",
                                                "preprocessing", "donor", "training_inputs"}
        assert type(row["dimension"]) is int and row["dimension"] in (384, 768)
        assert row["training_recipe_name"] in ("normative-wording-zero", "normative-wording-ce")
        assert row["id"] == str(row["dimension"]) + "-" + row["training_recipe_name"]
        used.update(row[k] for k in ("checkpoint", "preprocessing", "donor", "training_inputs"))
    assert used == set(artifacts)
    raws, witnesses, physical = {}, {}, set()
    for key, pin in artifacts.items():
        assert type(key) is str and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key)
        assert type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
        assert type(pin["path"]) is str and type(pin["bytes"]) is int
        assert 0 < pin["bytes"] <= 32 * 1024**2 and type(pin["sha256"]) is str
        assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
        assert pin["path"] not in physical
        physical.add(pin["path"])
        raw, witness = read(pin["path"], 32 * 1024**2)
        assert len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"]
        raws[key], witnesses[key] = raw, witness
    assert sum(len(raw) for raw in raws.values()) <= 64 * 1024**2
    exports = Path(exports_path)
    assert exports.is_absolute() and exports.name == "checkpoint-binding" and exports.parent.name == "exports"
    assert exports.parent.resolve(strict=True) == exports.parent
    assert all(stat.S_ISDIR(p.lstat().st_mode) for p in exports.parents)
    exports.mkdir(mode=0o700, exist_ok=True)
    assert exports.resolve(strict=True) == exports and stat.S_ISDIR(exports.lstat().st_mode)
    yield dict(artifacts=artifacts, cases={row["id"]: row for row in cases}, raws=raws, exports=exports)
    assert read(manifest_path, 131072) == (manifest_raw, manifest_witness)
    for key, pin in artifacts.items():
        raw, witness = read(pin["path"], 32 * 1024**2)
        assert raw == raws[key] and witness == witnesses[key]


@pytest.mark.parametrize("case_id", [
    "384-normative-wording-zero", "384-normative-wording-ce",
    "768-normative-wording-zero", "768-normative-wording-ce",
], ids=["384-normative-wording-zero", "384-normative-wording-ce",
        "768-normative-wording-zero", "768-normative-wording-ce"])
def test_checkpoint_conditioning_retained_original_artifact_lineage(_checkpoint_conditioning_retained_inputs, case_id):
    data = _checkpoint_conditioning_retained_inputs
    case, artifacts = data["cases"][case_id], data["artifacts"]
    raw = {k: data["raws"][case[k]] for k in ("checkpoint", "preprocessing", "donor", "training_inputs")}
    options = {"expected_" + k + "_sha256": artifacts[case[k]]["sha256"] for k in raw}
    report = compatibility.inspect_normative_checkpoint_conditioning_v1(raw["checkpoint"], raw["preprocessing"],
        raw["donor"], raw["training_inputs"], training_recipe_name=case["training_recipe_name"], **options)
    assert report["dimension"] == case["dimension"]
    assert report["training_recipe_name"] == case["training_recipe_name"]
    assert report["original_training_provenance_bound"] is True
    assert report["training_counts"] == {"train": 48, "validation": 48}
    for field, value in options.items():
        assert report["artifact_raw_sha256"][field[len("expected_"):-len("_sha256")]] == value
    if case["dimension"] == 384:
        assert report["head_contract"]["producer"] is report["head_contract"]["basis"] is None
        assert "recorded_training_profile_unprovided" in report["unresolved"]
    _checkpoint_conditioning_assert_unqualified(report)
    destination = data["exports"] / (case_id + ".json")
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        __import__("os").fsync(stream.fileno())
    assert json.loads(destination.read_bytes()) == report
