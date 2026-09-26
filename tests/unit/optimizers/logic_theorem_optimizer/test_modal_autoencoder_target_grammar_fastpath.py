"""Native summary inspection must preserve rich targets and live mutations."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as autoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import (
    LegalIRGrammarDecoder, LegalIRGrammarRejection, LegalIRGrammarValidation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import RichLegalIRTarget
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample


class InheritedTarget(LegalIRTrainingTarget):
    """Use the unchanged generic route as a reference for the native route."""


@pytest.fixture
def sample():
    return build_us_code_sample(title="5", section="grammar", text="The agency shall retain the record.")


def _target(sample, target_type=LegalIRTrainingTarget):
    document = LegalIRDocument(
        sample.sample_id, sample.text, sample.normalized_text,
        views={"deontic.ir": LogicIRView("deontic.ir", {"rules": [{"modality": "obligation"}]})},
        metadata={"created_at": "exact-fixture-time", "nested": {"revision": 1}})
    return target_type(("deontic_norms",), document,
        {"fixture_loss": 0.25, "legal_ir_grammar_accepted": 0.25},
        {"deontic_norms": {"fixture_loss": 0.25}},
        {"deontic.ir": 0.5, "zero": 0.0, "negative": -0.25}, False)


def _reference(target):
    return InheritedTarget(target.bridge_names, target.document, target.losses,
                           target.adapter_losses, target.view_distribution, target.accepted)


def _payload(sample, target):
    return autoencoder._legal_ir_target_payload([sample], legal_ir_targets={sample.sample_id: target})


def _grammar(target, text="The agency shall retain the record."):
    return autoencoder._legal_ir_grammar_validation_from_target(
        target, decoder=LegalIRGrammarDecoder(), source_text=text)


def _candidate():
    return {"family": "deontic", "rules": [{"modality": "invalid", "subject": "agency", "action": "retain"}]}


def _candidate_mapping():
    return {"family": "deontic", "candidate_ir": _candidate()}


def test_native_summary_avoids_serialization_and_matches_full_generic_payload(sample, monkeypatch):
    target = _target(sample)
    calls = []
    original = autoencoder._target_mapping

    def observe(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(autoencoder, "_target_mapping", observe)
    actual = _payload(sample, target)
    assert calls == []
    expected = _payload(sample, _reference(target))
    assert len(calls) == 2
    assert actual == expected
    assert actual["target_hashes"] == {sample.sample_id: target.document.canonical_hash()}
    assert actual["grammar_losses"] == {}


def test_native_losses_views_and_nested_document_mutations_remain_visible(sample):
    target = _target(sample)
    first = _payload(sample, target)
    target.losses["fixture_loss"] = 0.75
    target.losses["new_loss"] = 0.125
    target.view_distribution["deontic.ir"] = 0.25
    target.view_distribution["new_view"] = 0.5
    target.document.metadata["nested"]["revision"] = 2
    target.document.views["deontic.ir"].payload["rules"][0]["modality"] = "permission"
    current = _payload(sample, target)
    assert current == _payload(sample, _reference(target))
    assert current["target_hashes"] != first["target_hashes"]
    assert current["losses"]["fixture_loss"] == 0.75
    assert current["losses"]["new_loss"] == 0.125
    assert current["view_distribution"]["negative"] == -0.25
    assert current["view_distribution"]["zero"] == 0.0
    assert "negative" not in current["target_view_distributions_by_sample"][sample.sample_id]


@pytest.mark.parametrize("attribute", ["grammar_validation", "legal_ir_grammar_validation"])
@pytest.mark.parametrize("mapping", [False, True])
def test_native_explicit_grammar_precedence_and_rejections_remain_complete(sample, attribute, mapping):
    target = _target(sample)
    candidate = _candidate()
    rejection = LegalIRGrammarRejection("fixture_rejection", "$.rules[0]", "deontic", "rule", "exact detail")
    validation = LegalIRGrammarValidation(False, "deontic", candidate, (rejection,), ("chosen",), ("masked",))
    value = {"accepted": False, "family": "deontic", "rejection_reasons": [rejection.to_dict()],
             "selected_productions": ["chosen"], "masked_productions": ["masked"]} if mapping else validation
    object.__setattr__(target, attribute, value)
    object.__setattr__(target, "candidate_ir", candidate)
    observed = _grammar(target)
    assert observed.rejection_reasons == (rejection,)
    assert observed.selected_productions == ("chosen",)
    assert observed.masked_productions == ("masked",)
    payload = _payload(sample, target)
    assert payload["grammar_rejection_reasons_by_sample"][sample.sample_id] == [rejection.to_dict()]
    assert payload["target_losses_by_sample"][sample.sample_id]["legal_ir_grammar_accepted"] == 0.0
    assert payload["losses"]["legal_ir_grammar_accepted"] == 0.125
    object.__delattr__(target, attribute)
    assert _grammar(target) is None


def test_subclass_to_dict_override_stays_on_generic_candidate_path(sample):
    calls = []

    class CustomTarget(LegalIRTrainingTarget):
        def to_dict(self):
            calls.append(self)
            return _candidate_mapping()

    target = _target(sample, CustomTarget)
    validation = _grammar(target)
    assert len(calls) == 2
    assert validation == LegalIRGrammarDecoder().validate(_candidate(), family="deontic", source_text=sample.text)


def test_instance_to_dict_override_stays_on_generic_candidate_path(sample):
    target = _target(sample)
    calls = []

    def custom():
        calls.append(True)
        return _candidate_mapping()

    object.__setattr__(target, "to_dict", custom)
    validation = _grammar(target)
    assert len(calls) == 2
    assert validation.accepted is False
    assert validation.rejection_reasons


def test_class_to_dict_override_stays_on_generic_candidate_path(sample, monkeypatch):
    target = _target(sample)
    calls = []

    def custom(self):
        calls.append(self)
        return _candidate_mapping()

    monkeypatch.setattr(LegalIRTrainingTarget, "to_dict", custom)
    validation = _grammar(target)
    assert len(calls) == 2
    assert validation.accepted is False
    assert validation.rejection_reasons


def test_rich_candidate_changes_are_revalidated_without_cached_results():
    target = RichLegalIRTarget(_candidate_mapping())
    first = _grammar(target)
    target.candidate_ir["rules"][0]["modality"] = "obligation"
    second = _grammar(target)
    expected = LegalIRGrammarDecoder().validate(target.candidate_ir, family="deontic",
        source_text="The agency shall retain the record.")
    assert second == expected
    assert first.accepted is False
    assert second != first


def test_generic_dynamic_to_dict_keeps_the_second_observation():
    observations = []

    def dynamic():
        observations.append(True)
        return {} if len(observations) == 1 else _candidate_mapping()

    target = SimpleNamespace(to_dict=dynamic)
    validation = _grammar(target)
    assert len(observations) == 2
    assert validation.accepted is False
    assert validation.rejection_reasons


def test_missing_native_module_uses_generic_path_without_import(sample, monkeypatch):
    target = _target(sample)
    monkeypatch.delitem(sys.modules, "ipfs_datasets_py.logic.bridge.multiview")
    calls = []
    original = autoencoder._target_mapping
    monkeypatch.setattr(autoencoder, "_target_mapping", lambda value: (calls.append(value), original(value))[1])
    assert _grammar(target) is None
    assert len(calls) == 2
    assert "ipfs_datasets_py.logic.bridge.multiview" not in sys.modules
