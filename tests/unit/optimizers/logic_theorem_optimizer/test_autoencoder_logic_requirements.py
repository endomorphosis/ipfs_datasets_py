"""Requirements are source-derived declarations, never proof receipts."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

if os.environ.get("LOGIC_FLOOR_STAGING"):
    path = Path(os.environ["LOGIC_FLOOR_STAGING"]) / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_logic_requirements.py"
    name = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_logic_requirements"
    spec = importlib.util.spec_from_file_location(name, path)
    q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(q)
else:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_logic_requirements as q


@pytest.mark.parametrize("domain", q.DOMAINS)
def test_every_domain_has_distinct_eight_schema_capabilities_and_lake(domain):
    result = q.describe_logic_requirements(domain)
    rows = {row["requirement_id"]: row for row in result["logic_floor"]}
    assert len(rows) == 8
    assert set(rows) == {"first_order_logic", "temporal_deontic_first_order_logic",
        "deontic_first_order_logic", "temporal_first_order_logic", "cognitive_event_calculus",
        "deontic_cognitive_event_calculus", "frame_logic", "propositional_logic"}
    assert all(row["required"] for row in rows.values())
    assert all(row["scope"] == "schema_capability_not_universal_per_span_translation" for row in rows.values())
    lake = result["lake_schema_requirement"]
    assert lake["required"] and lake["command_template"] == ["lake", "build", "<Lib>"]
    assert not lake["mathlib_allowed"] and not lake["downloads_allowed"]
    assert not lake["fingerprint_only_theorem_satisfies_requirement"]
    assert not lake["successful_schema_build_proves_source_meaning"]
    assert all(result[key] is False for key in q.FALSE)
    assert result["qualification_gaps"]


def test_compositions_do_not_alias_cec_to_dcec_or_temporal_to_tdfol():
    rows = {row["requirement_id"]: row for row in q.describe_logic_requirements("legal_ir")["logic_floor"]}
    cec, dcec = rows["cognitive_event_calculus"], rows["deontic_cognitive_event_calculus"]
    assert cec["composition"] is None and cec["binding_gaps"]
    assert {item["family_id"] for item in cec["canonical_families"]} == {"event_calculus", "modal"}
    assert dcec["composition"]["family_id"] == "dcec"
    assert rows["temporal_first_order_logic"]["composition"]["family_id"] == "temporal"
    assert rows["temporal_deontic_first_order_logic"]["composition"]["family_id"] == "tdfol"


@pytest.mark.parametrize("domain", q.DOMAINS)
def test_code_extensions_come_from_actual_registered_routes(domain):
    from ipfs_datasets_py.logic.software_verification.syntax_bridge import default_ir_routes
    result = q.describe_logic_requirements(domain, contains_code=True)
    expected = sorted((row.to_dict() for row in default_ir_routes().values()), key=lambda row: row["kind"])
    assert len(expected) == 14
    assert [row["route"] for row in result["software_routes"]] == expected
    assert result["code_state_requirement"]["required"]
    assert result["code_state_requirement"]["profile"]["value"] == "tla_plus"
    assert result["code_state_requirement"]["profile"]["namespace"] == "profile"
    assert not result["code_state_requirement"]["bounded_model_check_is_unbounded_proof"]


def test_false_code_hint_never_waives_typed_code_outputs_and_security_is_mandatory():
    security = q.describe_logic_requirements("security_ir", contains_code=False)
    assert security["contains_code"] and len(security["software_routes"]) == 14
    intent = q.describe_logic_requirements("intent_ir")
    assert not intent["software_routes"] and intent["code_state_requirement"]["conditionally_required"]
    assert len(intent["code_requirement_trigger"]["conditional_route_ids"]) == 14
    assert intent["code_requirement_trigger"]["false_is_not_a_waiver"]


@pytest.mark.parametrize("domain", ["ui_ix_ir", "fol", "lake", "tla_plus", "safety", "", None, True])
def test_unknown_domains_and_taxonomy_roles_fail(domain):
    with pytest.raises(q.LogicRequirementError):
        q.describe_logic_requirements(domain)


@pytest.mark.parametrize("value", [0, 1, "true", None, [], {}])
def test_code_option_is_explicit_boolean(value):
    with pytest.raises(q.LogicRequirementError):
        q.describe_logic_requirements("legal_ir", contains_code=value)


def test_declarations_are_stable_detached_and_source_bound():
    first = q.describe_logic_requirements("ui_ux_ir")
    second = q.describe_logic_requirements("ui_ux_ir")
    assert first == second
    assert len(json.dumps(first).encode()) < q.MAX_BYTES
    assert len(first["requirements_sha256"]) == 64
    assert len(first["catalog_binding"]["source_identity"]["files"]) == 6
    first["logic_floor"].clear()
    assert len(q.describe_logic_requirements("ui_ux_ir")["logic_floor"]) == 8


def test_loss_contract_requires_decoding_and_separates_nondifferentiable_gates():
    result = q.describe_logic_requirements("legal_ir")
    loss = result["training_loss_requirements"]
    assert "conditions_and_exceptions" in loss["required_for_decoder_aware_training"]
    assert "free_running_decoded_output" in loss["selection_checks_required"]
    assert "source_bound_lake_schema_build" in loss["selection_checks_required"]
    assert "disjoint_tuning_evaluation" in loss["selection_checks_required"]
    assert loss["heldout_canary_required_for_generalization_claim"]
    assert not loss["heldout_canary_used_for_fit_or_selection"]
    assert not loss["lake_and_family_verifiers_are_differentiable_losses"]
    assert not loss["embedding_cosine_alone_satisfies_requirement"]
    with pytest.raises(TypeError):
        q.describe_logic_requirements("legal_ir", passed=True)


def test_catalog_change_during_description_is_rejected(monkeypatch):
    count = 0
    original = q._source_identity
    def changing():
        nonlocal count
        count += 1
        return {**original(), "probe": count}
    monkeypatch.setattr(q, "_source_identity", changing)
    with pytest.raises(q.LogicRequirementError, match="sources changed"):
        q.describe_logic_requirements("legal_ir")


def test_canonical_tree_guard_precedes_catalog_description(monkeypatch):
    from ipfs_datasets_py.logic.autoformal import tree_pin
    def fail():
        raise tree_pin.LogicTreePinError("drifted parser")
    monkeypatch.setattr(tree_pin, "require_workspace_logic_tree", fail)
    with pytest.raises(tree_pin.LogicTreePinError, match="drifted parser"):
        q.describe_logic_requirements("legal_ir")


def test_catalog_cannot_be_taken_from_a_separate_package(monkeypatch, tmp_path):
    foreign = tmp_path / "ipfs_datasets_py/logic/families/registry.py"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("# foreign catalog\n")
    monkeypatch.setattr(q.registry, "__file__", str(foreign))
    with pytest.raises(q.LogicRequirementError, match="outside canonical workspace"):
        q.describe_logic_requirements("legal_ir")
