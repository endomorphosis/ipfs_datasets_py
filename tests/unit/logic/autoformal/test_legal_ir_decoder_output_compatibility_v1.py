"""Authored output consistency controls grant no numerical or legal authority.

The receipt hashes below describe synthetic declarations, not computed logits or
retained checkpoint state. Genuine existing codec/inspection owners run only in
the root's native qualification; these tests do not generate with a model.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_ir_decoder_output_compatibility_v1 as owner
from ipfs_datasets_py.logic.formalization.autoencoder import gte_decoder_source_generation as source
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as formula


ROOT = Path(__file__).resolve().parents[4]
GENERATION_PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_source_generation.py"
VOCABULARY = ['<pad>', '<bos>', '<eos>', '"F"', '"O"', '"P"', '"action"',
    '"actor"', '"approve"', '"archive"', '"conditions"', '"deliver"', '"examine"',
    '"exceptions"', '"modality"', '"notary"', '"notice"', '"object"', '"preserve"',
    '"publish"', '"registrar"', '"rules"', '"secretary"', '"temporal"', '"treasurer"',
    '"trustee"', ',', ':', '[', ']', '{', '}']
CODEC = {"schema": "typed-json-lexical/v1", "target_vocabulary": VOCABULARY}


def rule(modality="O", actor="trustee", action="approve", obj="archive", **facets):
    return {"modality": modality, "actor": actor, "action": action, "object": obj,
            "conditions": [], "exceptions": [], "temporal": [], **facets}


def prediction(identity, rules):
    """Small authored lexical fixture; no existing test file is executed."""
    text = json.dumps({"rules": rules}, separators=(",", ":"), sort_keys=True)
    tokens = re.findall(r'"[^"\\]*"|[{}\[\]:,]', text)
    return {"id": identity, "token_ids": [VOCABULARY.index(token) for token in tokens],
            "eos_reached": True, "generation_status": "eos"}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def transport(value):
    return json.dumps(value, sort_keys=True, indent=2,
                      ensure_ascii=True, allow_nan=False).encode("utf-8") + b"\n"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def authored_receipt(ids, codec, *, variant="donor384", head="primary384"):
    """A consistent declared prefix chain; never numerical execution evidence."""
    width = source.VARIANTS[variant][head]
    vector = [1.0] + [0.0] * (width - 1)
    input_pin = digest(vector)
    terminated = ids[-1] == 2
    receipt = {
        "schema": source.SCHEMA, "variant": variant, "head": head,
        "input_dimension": width, "input_vector_sha256": input_pin,
        "numerical_input_sha256": input_pin,
        "max_new_tokens": len(ids) - 1,
        "inherited_max_target_tokens": 512 if head == "primary384" else 64,
        "effective_max_new_tokens": len(ids) - 1,
        "vocabulary_size": len(codec["target_vocabulary"]),
        "generated_ids": deepcopy(ids), "generated_ids_sha256": digest(ids),
        "terminated": terminated, "truncated": not terminated,
        "stop_reason": "eos" if terminated else "token_limit",
        "steps": [{
            "step": index, "prefix_length": index,
            "prefix_sha256": digest(ids[:index]), "input_vector_sha256": input_pin,
            "raw_logits_sha256": sha(("authored uncomputed logits:" + str(index)).encode()),
            "next_token_id": token,
        } for index, token in enumerate(ids[1:], 1)],
        "step_count": len(ids) - 1, "numerical_profile": deepcopy(source.NUMERICAL_PROFILE),
        "optimizer_steps": 0, "implementation_sha256": sha(GENERATION_PATH.read_bytes()),
        **{name: True for name in source.TRUE_FLAGS},
        **{name: False for name in source.FALSE_FLAGS},
    }
    for stem in ("model_state", "model_buffers", "gradient_state"):
        pin = sha(("authored uncomputed " + stem).encode())
        receipt[stem + "_sha256_before"] = pin
        receipt[stem + "_sha256_after"] = pin
    return receipt


def lexical_parts(*rules, variant="donor384"):
    codec = deepcopy(CODEC)
    generated = prediction("authored-output", list(rules) or [rule()])
    ids = [1, *generated["token_ids"], 2]
    return authored_receipt(ids, codec, variant=variant), codec


def legacy_parts(*, variant="legacy8", target_rule=None):
    target = {"rules": [rule() if target_rule is None else target_rule]}
    # Public fitting constructs only this explicitly authored fixture. The
    # compatibility adapter must use its supplied full codec without refitting.
    codec = formula.fit_codec([{
        "id": "authored-codec-control", "source_text": "latent", "canonical_ir": target,
    }])
    ids = formula.encode_target(codec, target)
    return authored_receipt(ids, codec, variant=variant, head="legacy8"), codec


@pytest.mark.parametrize("kind,variant", [
    ("lexical", "donor384"), ("lexical", "student768"),
    ("legacy", "legacy8"), ("legacy", "student768"),
], ids=["original-primary384", "native768-primary", "original-legacy8", "native768-auxiliary"])
def test_authored_fixtures_are_only_consistent_receipt_declarations(kind, variant):
    receipt, _ = (lexical_parts(variant=variant) if kind == "lexical"
                  else legacy_parts(variant=variant))
    imported_before = set(sys.modules)
    inspected = source.inspect_source_only_generation(receipt)
    assert inspected["execution_authenticated"] is False
    assert inspected["teacher_qualified"] is inspected["proof_authority"] is False
    assert inspected["generation_sha256"] == digest(receipt)
    assert not {"torch", "numpy", "transformers"} & (set(sys.modules) - imported_before)


def case_for(receipt, codec, *, serializer=transport, **capture_changes):
    receipt_raw, codec_raw = serializer(receipt), serializer(codec)
    capture = {
        "schema": "legal-ir-decoder-capture-binding/v1", "id": "authored-output",
        "source_sha256": sha(b"authored source identity; source not passed to decoding"),
        "control": "source", "head": receipt["head"], "variant": receipt["variant"],
        "dimension": receipt["input_dimension"],
        "checkpoint_sha256": sha(b"authored checkpoint declaration; not loaded"),
        "model_state_sha256": receipt["model_state_sha256_before"],
        "input_vector_sha256": receipt["input_vector_sha256"],
        "numerical_input_sha256": receipt["numerical_input_sha256"],
        "receipt_sha256": sha(receipt_raw), "codec_sha256": sha(codec_raw),
        **capture_changes,
    }
    return receipt_raw, codec_raw, serializer(capture)


def pins(raws):
    return dict(zip(("expected_receipt_sha256", "expected_codec_sha256",
                     "expected_capture_binding_sha256"), map(sha, raws)))


def prepare(raws, **changes):
    return owner.prepare_legal_ir_decoder_output_compatibility_v1(*raws, **{**pins(raws), **changes})


def validate(report, raws, **changes):
    return owner.validate_legal_ir_decoder_output_compatibility_v1(report, *raws,
        **{**pins(raws), "expected_report_sha256":
           owner.legal_ir_decoder_output_compatibility_sha256(report), **changes})


def no_authority(report):
    assert report["execution_authenticated"] is False
    assert all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is type(report["evaluation_gold_mask"]) is int
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["rich_relational_compatibility"] == {
        "supported": False, "status": "unsupported_profile",
        "reason": "emitted_format_outside_relational_profile",
        "request_utf8": None, "request_sha256": None,
    }
    assert not any("encoder" in key for key in report["capture_binding"])


def inspection_errors(report):
    errors = report["legacy_output"]["inspection_errors"]
    assert type(errors) is list
    assert all(type(error) is str and 0 < len(error) <= 512 for error in errors)
    return errors


@pytest.mark.parametrize("kind,variant", [
    ("lexical", "donor384"), ("lexical", "student768"),
    ("legacy", "legacy8"), ("legacy", "student768"),
], ids=["primary384-lexical", "native768-lexical", "legacy8-tagged", "native768-tagged"])
def test_valid_existing_outputs_keep_native_and_rich_compatibility_separate(kind, variant):
    receipt, codec = (lexical_parts(variant=variant) if kind == "lexical"
                      else legacy_parts(variant=variant))
    raws = case_for(receipt, codec)
    report = prepare(raws)
    assert set(report) == {
        "schema", "profile", "status", "inputs", "capture_binding", "generation", "legacy_output",
        "rich_relational_compatibility", "producer_pins", "authority", "execution_authenticated",
        "training_mask", "evaluation_gold_mask", "limitations",
    }
    assert report["schema"] == "legal-ir-decoder-output-compatibility/v1"
    assert report["profile"] == "preserved-donor-output-versus-relational-request/v1"
    assert report["status"] == "candidate_output_inspected_relational_profile_unsupported"
    assert report["inputs"] == {
        name: {"sha256": sha(raw), "bytes": len(raw)}
        for name, raw in zip(("receipt", "codec", "capture_binding"), raws)
    }
    assert report["generation"]["generated_ids"] == receipt["generated_ids"]
    assert report["generation"]["input_vector_sha256"] == receipt["input_vector_sha256"]
    assert report["generation"]["numerical_input_sha256"] == receipt["numerical_input_sha256"]
    assert report["generation"]["model_state_sha256"] == receipt["model_state_sha256_before"]
    assert set(report["generation"]) == {
        "variant", "head", "input_dimension", "input_vector_sha256", "numerical_input_sha256",
        "model_state_sha256", "generated_ids", "generated_ids_sha256", "terminated", "truncated",
        "stop_reason", "inherited_max_target_tokens", "effective_max_new_tokens", "receipt_inspection_sha256",
    }
    native = report["legacy_output"]
    assert native["grammar_valid"] is native["complete_candidate"] is True
    assert native["ordered_generated_ir"] == {"rules": [rule()]}
    assert inspection_errors(report) == []
    if kind == "lexical":
        assert native["canonicalization_checked"] is True
        assert native["canonical_contract_ir"] == native["ordered_generated_ir"]
        assert native["canonicalization_changed_payload"] is False
    else:
        assert native["canonicalization_checked"] is False
        assert native["canonical_contract_ir"] is native["canonicalization_changed_payload"] is None
    no_authority(report)
    validate(report, raws)


def test_original_raw_transports_are_committed_separately_from_parsed_content():
    receipt, codec = lexical_parts()
    pretty_raws, compact_raws = case_for(receipt, codec), case_for(receipt, codec, serializer=wire)
    assert [sha(raw) for raw in pretty_raws] != [sha(raw) for raw in compact_raws]
    pretty, compact = prepare(pretty_raws), prepare(compact_raws)
    assert pretty["inputs"] != compact["inputs"]
    assert pretty["capture_binding"]["receipt_sha256"] == sha(pretty_raws[0])
    assert compact["capture_binding"]["receipt_sha256"] == sha(compact_raws[0])
    assert pretty["capture_binding"]["codec_sha256"] == sha(pretty_raws[1])
    assert compact["capture_binding"]["codec_sha256"] == sha(compact_raws[1])
    assert pretty["generation"] == compact["generation"]
    assert pretty["legacy_output"] == compact["legacy_output"]
    assert owner.legal_ir_decoder_output_compatibility_sha256(pretty) != \
           owner.legal_ir_decoder_output_compatibility_sha256(compact)
    with pytest.raises(ValueError):
        validate(pretty, compact_raws)


def test_capture_source_and_checkpoint_are_committed_declarations_not_verified_assets():
    receipt, codec = lexical_parts(variant="student768")
    original_raws = case_for(receipt, codec)
    changed_raws = case_for(receipt, codec, source_sha256="a" * 64,
                           checkpoint_sha256="b" * 64, control="authored-zero-control")
    original, changed = prepare(original_raws), prepare(changed_raws)
    assert original["capture_binding"] != changed["capture_binding"]
    assert original["generation"] == changed["generation"]
    assert original["legacy_output"] == changed["legacy_output"]
    no_authority(original)
    no_authority(changed)


@pytest.mark.parametrize("key", [
    "expected_receipt_sha256", "expected_codec_sha256", "expected_capture_binding_sha256",
], ids=["receipt-raw-pin", "full-codec-raw-pin", "capture-raw-pin"])
def test_each_input_needs_its_independent_original_raw_pin(key):
    raws = case_for(*lexical_parts())
    with pytest.raises(ValueError):
        prepare(raws, **{key: "f" * 64})


@pytest.mark.parametrize("field,value", [
    ("receipt_sha256", "a" * 64), ("codec_sha256", "b" * 64),
    ("dimension", 768), ("dimension", True), ("head", "legacy8"),
    ("variant", "student768"), ("model_state_sha256", "c" * 64),
    ("input_vector_sha256", "d" * 64), ("numerical_input_sha256", "e" * 64),
], ids=["receipt-binding", "codec-binding", "input-width", "boolean-width", "head",
        "variant", "model-state", "raw-input-vector", "numerical-input-vector"])
def test_capture_cannot_disagree_with_receipt_or_independent_transport_pins(field, value):
    with pytest.raises(ValueError):
        prepare(case_for(*lexical_parts(), **{field: value}))


@pytest.mark.parametrize("field,value", [
    ("encoder_sha256", "a" * 64), ("reference", {"rules": [rule()]}),
    ("execution_authenticated", True), ("latent_only_verified", True),
    ("request_utf8", "invented relational output"),
], ids=["invented-encoder", "reference-channel", "execution-authority",
        "latent-verification", "invented-relational-request"])
def test_closed_capture_does_not_accept_extra_provenance_or_target_channels(field, value):
    with pytest.raises(ValueError):
        prepare(case_for(*lexical_parts(), **{field: value}))


@pytest.mark.parametrize("kind,mutation", [
    ("legacy", "missing-policy"), ("legacy", "missing-source-vocabulary"),
    ("legacy", "wrong-policy"), ("legacy", "wrong-source-order"),
    ("lexical", "extra-policy"), ("lexical", "duplicate-vocabulary"),
    ("lexical", "wrong-special-order"), ("lexical", "receipt-vocabulary-size"),
], ids=["tagged-policy-required", "tagged-source-vocabulary-required", "tagged-policy-exact",
        "tagged-source-order-exact", "lexical-closed-schema", "lexical-token-uniqueness",
        "lexical-special-ids", "receipt-full-vocabulary-binding"])
def test_original_full_codec_and_its_declared_profile_are_required(kind, mutation):
    receipt, codec = legacy_parts() if kind == "legacy" else lexical_parts()
    if mutation == "missing-policy":
        del codec["policy"]
    elif mutation == "missing-source-vocabulary":
        del codec["source_vocabulary"]
    elif mutation == "wrong-policy":
        codec["policy"]["generation_fallback"] = "repair"
    elif mutation == "wrong-source-order":
        codec["source_vocabulary"] = ["latent", "<pad>", "<unk>"]
    elif mutation == "extra-policy":
        codec["policy"] = {"invented": True}
    elif mutation == "duplicate-vocabulary":
        codec["target_vocabulary"][4] = codec["target_vocabulary"][3]
    elif mutation == "wrong-special-order":
        codec["target_vocabulary"][:3] = ["<bos>", "<pad>", "<eos>"]
    elif mutation == "receipt-vocabulary-size":
        receipt["vocabulary_size"] += 1
    with pytest.raises(ValueError):
        prepare(case_for(receipt, codec))


@pytest.mark.parametrize("head", ["primary384", "legacy8"], ids=["tagged-is-not-lexical", "lexical-is-not-tagged"])
def test_other_heads_codec_is_not_reinterpreted_or_reconstructed(head):
    _, codec = legacy_parts() if head == "primary384" else lexical_parts()
    receipt = authored_receipt([1, 2], codec,
        variant="donor384" if head == "primary384" else "legacy8", head=head)
    with pytest.raises(ValueError):
        prepare(case_for(receipt, codec))


@pytest.mark.parametrize("head,cap,reason", [
    ("primary384", 513, "lexical_target_token_budget_exceeded"),
    ("legacy8", 65, "legacy_target_token_budget_exceeded"),
], ids=["lexical-inherited-budget", "tagged-inherited-budget"])
def test_profile_budget_overflow_remains_native_output_failure(head, cap, reason):
    receipt, codec = lexical_parts() if head == "primary384" else legacy_parts()
    receipt["inherited_max_target_tokens"] = cap
    report = prepare(case_for(receipt, codec))
    assert report["generation"]["generated_ids"] == receipt["generated_ids"]
    assert report["legacy_output"]["grammar_valid"] is False
    assert report["legacy_output"]["complete_candidate"] is False
    assert reason in report["legacy_output"]["reason_codes"]
    assert inspection_errors(report) == []
    no_authority(report)


@pytest.mark.parametrize("kind,bad_token", [
    ("lexical", 0), ("lexical", 1), ("legacy", 0), ("legacy", 1),
], ids=["lexical-interior-pad", "lexical-interior-bos", "tagged-interior-pad", "tagged-interior-bos"])
def test_raw_invalid_special_tokens_are_preserved_instead_of_filtered(kind, bad_token):
    receipt, codec = legacy_parts() if kind == "legacy" else lexical_parts()
    ids = deepcopy(receipt["generated_ids"])
    ids.insert(2, bad_token)
    receipt = authored_receipt(ids, codec, variant=receipt["variant"], head=receipt["head"])
    report = prepare(case_for(receipt, codec))
    assert report["generation"]["generated_ids"] == ids
    assert report["legacy_output"]["grammar_valid"] is False
    assert report["legacy_output"]["complete_candidate"] is False
    if kind == "lexical":
        assert report["legacy_output"]["reason_codes"] == ["lexical_generated_output_invalid"]
        assert inspection_errors(report) == ["generated token outside content vocabulary or output budget"]
    else:
        assert report["legacy_output"]["reason_codes"] == ["legacy_codec_rejected_generated_tokens"]
        assert inspection_errors(report) == ["target atom belongs to another field or is structural"]
    no_authority(report)


@pytest.mark.parametrize("kind", ["lexical", "legacy"], ids=["lexical-cap", "tagged-cap"])
def test_cap_without_eos_cannot_become_a_complete_candidate(kind):
    receipt, codec = legacy_parts() if kind == "legacy" else lexical_parts()
    ids = receipt["generated_ids"][:-1]
    receipt = authored_receipt(ids, codec, variant=receipt["variant"], head=receipt["head"])
    report = prepare(case_for(receipt, codec))
    assert report["generation"]["generated_ids"] == ids
    assert report["generation"]["terminated"] is False
    assert report["generation"]["truncated"] is True
    assert report["generation"]["stop_reason"] == "token_limit"
    assert report["legacy_output"]["complete_candidate"] is False
    if kind == "lexical":
        assert report["legacy_output"]["ordered_generated_ir"] == {"rules": [rule()]}
        assert inspection_errors(report) == []
    else:
        assert inspection_errors(report) == ["target is incomplete; all facets and EOS are required"]
    no_authority(report)


@pytest.mark.parametrize("kind", ["lexical", "legacy"], ids=["lexical-early-eos", "tagged-early-eos"])
def test_eos_after_bos_retains_an_invalid_empty_output(kind):
    _, codec = legacy_parts() if kind == "legacy" else lexical_parts()
    receipt = authored_receipt([1, 2], codec,
        variant="legacy8" if kind == "legacy" else "donor384",
        head="legacy8" if kind == "legacy" else "primary384")
    report = prepare(case_for(receipt, codec))
    assert report["generation"]["generated_ids"] == [1, 2]
    assert report["legacy_output"]["grammar_valid"] is False
    assert report["legacy_output"]["complete_candidate"] is False
    errors = inspection_errors(report)
    if kind == "lexical":
        assert len(errors) == 1 and errors[0].startswith("Expecting value:")
    else:
        assert errors == ["target field order or marker differs"]
    no_authority(report)


def test_lexical_canonicalization_changes_remain_separate_from_generated_payload():
    generated_rule = rule(conditions=["notary", "notary"])
    report = prepare(case_for(*lexical_parts(generated_rule)))
    native = report["legacy_output"]
    assert native["grammar_valid"] is native["complete_candidate"] is True
    assert native["ordered_generated_ir"] == {"rules": [generated_rule]}
    assert native["canonical_contract_ir"]["rules"][0]["conditions"] == ["notary"]
    assert native["canonicalization_checked"] is native["canonicalization_changed_payload"] is True
    assert inspection_errors(report) == []
    no_authority(report)


def test_ordered_lexical_rule_sequence_is_not_replaced_by_native_sorted_order():
    rules = [rule(), rule("F", "notary", "publish", "notice")]
    report = prepare(case_for(*lexical_parts(*rules)))
    native = report["legacy_output"]
    assert native["ordered_generated_ir"] == {"rules": rules}
    assert native["canonical_contract_ir"] != native["ordered_generated_ir"]
    assert native["canonicalization_changed_payload"] is True
    assert inspection_errors(report) == []
    no_authority(report)


def test_tagged_duplicate_qualifiers_are_rejected_without_canonical_normalization():
    receipt, codec = legacy_parts(target_rule=rule(conditions=["notary"]))
    token = codec["target_vocabulary"].index(wire(["atom", "conditions", "notary"]).decode())
    ids = deepcopy(receipt["generated_ids"])
    position = ids.index(token)
    ids.insert(position + 1, token)
    receipt = authored_receipt(ids, codec, variant="legacy8", head="legacy8")
    report = prepare(case_for(receipt, codec))
    native = report["legacy_output"]
    assert report["generation"]["generated_ids"] == ids
    assert native["grammar_valid"] is native["complete_candidate"] is False
    assert native["canonicalization_checked"] is False
    assert native["canonical_contract_ir"] is native["canonicalization_changed_payload"] is None
    assert inspection_errors(report) == ["qualifier tokens must be sorted unique and at most four"]
    no_authority(report)


def test_valid_json_with_invalid_native_modality_is_not_autoformalized():
    invalid_rule = rule("rules")
    report = prepare(case_for(*lexical_parts(invalid_rule)))
    native = report["legacy_output"]
    assert native["ordered_generated_ir"] == {"rules": [invalid_rule]}
    assert native["grammar_valid"] is native["complete_candidate"] is False
    assert native["canonical_contract_ir"] is None
    assert inspection_errors(report) == ["modality must be O, P, or F under the measured v1 grammar"]
    no_authority(report)


@pytest.mark.parametrize("mutation", [
    "extra-field", "wrong-start", "interior-eos", "token-boolean", "token-range",
    "prefix-hash", "step-token", "input-step-hash", "implementation", "stop-flag", "changed-state",
    "encoder-executed", "proof-authority", "optimizer-step", "unknown-profile",
], ids=["closed-receipt", "bos-required", "nothing-after-eos", "integer-token-required",
        "vocabulary-bound", "prefix-chain", "step-selected-token", "step-input-binding",
        "producer-source-pin", "stop-consistency", "unchanged-state", "no-encoder-run",
        "no-proof-authority", "no-training-step", "fixed-numerical-profile"])
def test_malformed_receipt_is_refused_without_repair(mutation):
    receipt, codec = lexical_parts()
    if mutation == "extra-field":
        receipt["reference"] = {"rules": [rule()]}
    elif mutation == "wrong-start":
        receipt["generated_ids"][0] = 0
    elif mutation == "interior-eos":
        receipt["generated_ids"][2] = 2
    elif mutation == "token-boolean":
        receipt["generated_ids"][2] = True
    elif mutation == "token-range":
        receipt["generated_ids"][2] = len(codec["target_vocabulary"])
    elif mutation == "prefix-hash":
        receipt["steps"][1]["prefix_sha256"] = "a" * 64
    elif mutation == "step-token":
        receipt["steps"][0]["next_token_id"] = 0
    elif mutation == "input-step-hash":
        receipt["steps"][0]["input_vector_sha256"] = "b" * 64
    elif mutation == "implementation":
        receipt["implementation_sha256"] = "c" * 64
    elif mutation == "stop-flag":
        receipt["terminated"] = False
    elif mutation == "changed-state":
        receipt["model_state_sha256_after"] = "d" * 64
    elif mutation == "encoder-executed":
        receipt["encoder_executed"] = True
    elif mutation == "proof-authority":
        receipt["proof_authority"] = True
    elif mutation == "optimizer-step":
        receipt["optimizer_steps"] = 1
    elif mutation == "unknown-profile":
        receipt["numerical_profile"]["prefix_origin"] = "reference_prefix"
    with pytest.raises(ValueError):
        prepare(case_for(receipt, codec))


@pytest.mark.parametrize("slot,kind", [
    (0, "utf8"), (1, "utf8"), (2, "utf8"),
    (0, "duplicate-key"), (1, "duplicate-key"), (2, "duplicate-key"),
    (0, "nonfinite"), (1, "nonfinite"), (2, "nonfinite"),
    (0, "root-array"), (1, "root-array"), (2, "root-array"),
    (0, "overflow"), (1, "overflow"), (2, "overflow"),
    (0, "depth"), (1, "depth"), (2, "depth"),
], ids=["receipt-utf8", "codec-utf8", "capture-utf8", "receipt-duplicate-key",
        "codec-duplicate-key", "capture-duplicate-key", "receipt-nan", "codec-nan", "capture-nan",
        "receipt-object", "codec-object", "capture-object", "receipt-byte-bound", "codec-byte-bound",
        "capture-byte-bound", "receipt-depth-bound", "codec-depth-bound", "capture-depth-bound"])
def test_raw_input_bounds_and_json_shape_are_strict(slot, kind):
    raws = list(case_for(*lexical_parts()))
    bad = {
        "utf8": lambda: b"\xff",
        "duplicate-key": lambda: b'{"schema":"first","schema":"second"}',
        "nonfinite": lambda: b'{"x":NaN}',
        "root-array": lambda: b"[]",
        "overflow": lambda: b" " * ((128 * 1024 if slot == 2 else 4 * 1024 * 1024) + 1),
        "depth": lambda: b'{"x":' + b"[" * 100 + b"0" + b"]" * 100 + b"}",
    }[kind]()
    raws[slot] = bad
    if slot != 2:
        capture = json.loads(raws[2])
        capture["receipt_sha256"] = sha(raws[0])
        capture["codec_sha256"] = sha(raws[1])
        raws[2] = transport(capture)
    with pytest.raises(ValueError):
        prepare(tuple(raws))


@pytest.mark.parametrize("field,value", [
    ("id", ""), ("id", "x" * 257), ("id", "line\nfeed"),
    ("control", ""), ("control", "x" * 129), ("source_sha256", "A" * 64),
    ("checkpoint_sha256", None), ("schema", "legal-ir-decoder-capture-binding/v2"),
], ids=["nonempty-id", "bounded-id", "printable-id", "nonblank-control", "bounded-control",
        "lowercase-source-pin", "explicit-checkpoint-pin", "exact-capture-schema"])
def test_capture_is_bounded_closed_metadata(field, value):
    with pytest.raises(ValueError):
        prepare(case_for(*lexical_parts(), **{field: value}))


@pytest.mark.parametrize("mutation", [
    "authority", "execution", "mask", "gold-mask", "rich-support", "rich-request", "grammar",
    "generated-token", "source-binding", "extra-key",
], ids=["authority-reseal", "execution-reseal", "training-mask-reseal", "gold-mask-reseal",
        "rich-support-reseal", "invented-request-reseal", "native-result-reseal", "raw-token-reseal",
        "capture-source-reseal", "unknown-report-field"])
def test_full_report_resealing_cannot_bypass_regeneration(mutation):
    raws = case_for(*lexical_parts())
    report = prepare(raws)
    if mutation == "authority":
        report["authority"][next(iter(report["authority"]))] = True
    elif mutation == "execution":
        report["execution_authenticated"] = True
    elif mutation == "mask":
        report["training_mask"] = 1
    elif mutation == "gold-mask":
        report["evaluation_gold_mask"] = 1
    elif mutation == "rich-support":
        report["rich_relational_compatibility"]["supported"] = True
    elif mutation == "rich-request":
        report["rich_relational_compatibility"]["request_utf8"] = '{"invented":true}'
    elif mutation == "grammar":
        report["legacy_output"]["grammar_valid"] = False
    elif mutation == "generated-token":
        report["generation"]["generated_ids"][1] = 0
    elif mutation == "source-binding":
        report["capture_binding"]["source_sha256"] = "a" * 64
    elif mutation == "extra-key":
        report["new_trust_domain"] = True
    with pytest.raises(ValueError):
        validate(report, raws)


def test_uncomputed_logit_hash_change_requires_changed_input_report_even_after_resealing():
    receipt, codec = lexical_parts()
    first_raws = case_for(receipt, codec)
    first = prepare(first_raws)
    receipt["steps"][0]["raw_logits_sha256"] = "a" * 64
    second_raws = case_for(receipt, codec)
    second = prepare(second_raws)
    assert first["legacy_output"] == second["legacy_output"]
    assert first["execution_authenticated"] is second["execution_authenticated"] is False
    assert owner.legal_ir_decoder_output_compatibility_sha256(first) != \
           owner.legal_ir_decoder_output_compatibility_sha256(second)
    with pytest.raises(ValueError):
        validate(first, second_raws)


def test_independent_report_pin_is_required_for_replay_validation():
    raws = case_for(*lexical_parts())
    report = prepare(raws)
    with pytest.raises(ValueError):
        validate(report, raws, expected_report_sha256="f" * 64)
