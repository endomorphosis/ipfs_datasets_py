from copy import deepcopy
import hashlib
import pytest

from scripts.ops.legal_ir import audit_legal_decoder_codec_scope as audit


def rule(**values):
    return {"rules": [{"modality": "O", "actor": "agency", "action": "submit", "object": "reports",
        "conditions": [], "exceptions": [], "temporal": [], **values}]}


def primary_codec():
    tokens = set(audit.batch._json_tokens(rule()))
    return {"schema": "typed-json-lexical/v1", "target_vocabulary": ["<pad>", "<bos>", "<eos>", *sorted(tokens)]}


def legacy_codec():
    return audit.legacy.fit_codec([{"id": "x", "source_text": "latent", "canonical_ir": rule()}])


def example(target):
    return {"id": "x", "source_sha256": "a" * 64, "canonical_ir": target}


def test_primary_complete_strings_cannot_compose_new_identifier():
    result = audit.target_coverage([example(rule(actor="agency agency"))], primary_codec(), "primary384", 512)
    assert result["exact_target_representable"] == 0
    assert result["rows"][0]["missing_atoms_by_facet"]["actor"] == ["agency agency"]


def test_primary_known_strings_are_not_restricted_to_training_fields():
    # Schema key literals are also JSON string tokens. The strict scorer permits
    # them as scalar/qualifier values; they are not field-typed vocabulary atoms.
    target = rule(actor="conditions", action="rules", object="O", conditions=["actor"])
    result = audit.target_coverage([example(target)], primary_codec(), "primary384", 512)
    assert result["exact_target_representable"] == 1


def test_legacy_atoms_remain_field_typed():
    result = audit.target_coverage([example(rule(actor="reports"))], legacy_codec(), "legacy8", 64)
    assert result["exact_target_representable"] == 0
    assert result["rows"][0]["missing_atoms_by_facet"]["actor"] == ["reports"]


@pytest.mark.parametrize("kind,max_tokens", [("primary384", 512), ("legacy8", 64)])
def test_known_target_codec_roundtrip_and_budget(kind, max_tokens):
    codec = primary_codec() if kind == "primary384" else legacy_codec()
    result = audit.target_coverage([example(rule())], codec, kind, max_tokens)
    assert result["exact_target_representable"] == 1
    result = audit.target_coverage([example(rule())], codec, kind, 2)
    assert result["exact_target_representable"] == 0
    assert "budget" in result["rows"][0]["reason"]


def test_trained_interface_cannot_claim_changed_codec():
    p, l = primary_codec(), legacy_codec()
    hashes = {"primary384": audit.digest(p), "legacy8": audit.digest(l)}
    init = {"primary": {"codec": p}, "legacy8": {"codec": l},
        "donor_pins": {"teacher384_codec_sha256": hashes["primary384"], "legacy8_codec_sha256": hashes["legacy8"]}}
    assert audit.assert_interface_codecs(init, [{"codec_sha256": hashes}]) == hashes
    bad = deepcopy(hashes)
    bad["legacy8"] = "f" * 64
    with pytest.raises(ValueError, match="codec changed"):
        audit.assert_interface_codecs(init, [{"codec_sha256": bad}])


def test_statutory_source_bounds_and_literal_inventory_do_not_create_gold():
    source = "The agency shall submit reports."
    groups = [{"source_text": source, "source_text_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "gold_target": None, "training_qualified": False, "source_observations": [{}, {}]}]
    result = audit.source_diagnostics(groups, primary_codec(), legacy_codec())
    assert result["source_observations"] == 2 and result["span_tokenizer_accepted_groups"] == 1
    assert result["rows"][0]["semantic_coverage"] is None
    assert result["rows"][0]["exact_target_representability"] is None
    groups[0]["source_text"] = "changed"
    with pytest.raises(ValueError, match="hash differs"):
        audit.source_diagnostics(groups, primary_codec(), legacy_codec())


def test_span_training_interface_requires_unique_nonoverlapping_source_spans():
    good = {"id": "good", "source_text": "agency shall submit reports.", "canonical_ir": rule()}
    assert audit.span.audit_examples([good])["all_supported"]
    repeated = {**good, "source_text": "agency shall submit reports to agency."}
    assert "ambiguous" in audit.span.audit_examples([repeated])["rejected_rows"][0]["reason"]
    implicit = {**good, "canonical_ir": rule(actor="government")}
    assert "exact token-aligned" in audit.span.audit_examples([implicit])["rejected_rows"][0]["reason"]


def test_span_training_interface_rejects_multi_rule_or_multi_atom_scope():
    source = "agency shall submit reports if a and b."
    candidate = {"id": "x", "source_text": source, "canonical_ir": rule(conditions=["a", "b"])}
    assert "at most one" in audit.span.audit_examples([candidate])["rejected_rows"][0]["reason"]
    candidate["canonical_ir"] = {"rules": [rule()["rules"][0], rule()["rules"][0]]}
    assert "exactly one" in audit.span.audit_examples([candidate])["rejected_rows"][0]["reason"]
