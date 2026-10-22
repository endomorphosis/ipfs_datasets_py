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
