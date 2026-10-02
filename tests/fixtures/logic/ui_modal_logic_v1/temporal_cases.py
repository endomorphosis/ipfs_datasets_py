"""Authored compound UI state logic declarations; never learned predictions."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path


def descriptor(requirement_id, formulas=None, *, state_ids=("open", "closed")):
    from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_temporal_logic as owner
    initial_id, target_id = state_ids
    opened, closed = owner.state_symbol(initial_id), owner.state_symbol(target_id)
    if formulas is None:
        formulas = ([{"formula_id": "always-open", "formula": "G(UIState(" + opened + "))"},
                     {"formula_id": "eventually-closed", "formula": "◊(UIState(" + closed + "))"}]
            if requirement_id == "TFOL" else [
                {"formula_id": "state-obligation", "formula": "O(◊(UIState(" + closed + ")))"},
                {"formula_id": "state-permission", "formula": "P(X(UIState(" + opened + ")))"},
                {"formula_id": "state-prohibition", "formula": "F(G(UIState(" + opened + ")))"}])
    return {"schema": owner.DESCRIPTOR_SCHEMA, "time_semantics": deepcopy(owner.TIME_SEMANTICS),
        "deontic_semantics": owner.DEONTIC_SEMANTICS,
        "state_bindings": [{"symbol": opened, "state_id": initial_id}, {"symbol": closed, "state_id": target_id}],
        "formulas": deepcopy(formulas)}


def descriptors(ec_fixture=None):
    """Authored property template with identities joined to explicit fixture data.

    The normative choice is this fixture's declaration, never inferred from a
    transition. Only identifiers are read from the supplied native document.
    """
    state_ids = ("open", "closed")
    if ec_fixture is not None:
        document = ec_fixture["candidate"]["document"]
        state_ids = (document["initial_states"][0], document["transitions"][0]["target_state_id"])
        assert len(document["states"]) == 2 and set(state_ids) == {row["state_id"] for row in document["states"]}
    return {"temporal": descriptor("TFOL", state_ids=state_ids),
            "tdfol": descriptor("TDFOL", state_ids=state_ids), "dcec": None}


def make_case(identity="ui-state-temporal-and-deontic", *, base_index=1, logic=None):
    path = Path(__file__).resolve().parents[1] / "ui_declared_source_v1/cases.py"
    spec = importlib.util.spec_from_file_location("ui_modal_prior_declared_cases", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.cases()[base_index]
    previous = json.loads(original["source_text"])
    candidate = {"kind": "ui_declared_logic", "document": deepcopy(previous["document"]),
                 "logic": deepcopy(descriptors(original) if logic is None else logic)}
    source = {"schema": "ui-declared-logic-source/v1", "candidate": deepcopy(candidate),
              "interpretations": deepcopy(previous["interpretations"])}
    return {"id": identity, "domain": "ui_ux_ir", "source_text": json.dumps(source, sort_keys=True, separators=(",", ":")),
        "candidate": candidate, "candidate_origin": "authored_compound_UI_logic_not_learned_model_output",
        "model_inference_executed": False, "options": {}, "expected_disposition": "prepared",
        "expected_reason": None}


def cases():
    from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_temporal_logic as owner
    result = [make_case(), make_case("ui-state-temporal-idle", base_index=0,
        logic={"temporal": descriptor("TFOL"), "tdfol": None, "dcec": None}),
        make_case("ui-state-deontic-false-guard-idle", base_index=2,
            logic={"temporal": None, "tdfol": descriptor("TDFOL"), "dcec": None})]
    edits = [
        ("ui-state-unknown-reference-blocked", lambda c: c["logic"]["temporal"]["state_bindings"][0].update(state_id="missing"),
         "state binding"),
        ("ui-state-finite-future-default-blocked", lambda c: c["logic"]["temporal"]["time_semantics"].update(unobserved_future="false"),
         "arbitrary-continuation"),
        ("ui-state-modal-missing-temporal-blocked", lambda c: c["logic"]["tdfol"]["formulas"][0].update(
            formula="O(UIState(" + owner.state_symbol("closed") + "))"), "actual operators"),
        ("ui-state-unbound-predicate-blocked", lambda c: c["logic"]["temporal"]["formulas"][0].update(
            formula="G(Private(" + owner.state_symbol("open") + "))"), "UIState"),
    ]
    for identity, mutate, reason in edits:
        row = make_case(identity)
        mutate(row["candidate"])
        source = json.loads(row["source_text"])
        source["candidate"] = deepcopy(row["candidate"])
        row.update(source_text=json.dumps(source, sort_keys=True, separators=(",", ":")),
                   expected_disposition="blocked", expected_reason=reason)
        result.append(row)
    different = make_case("ui-state-source-only-norm-blocked")
    different["candidate"]["logic"]["tdfol"] = None
    different.update(expected_disposition="blocked", expected_reason="source_disagreement")
    result.append(different)
    return result


def prepare_case(row):
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_logic_source as adapter
    return adapter.prepare_family_targets(row["source_text"], row["candidate"])
