"""Explicit authored DCEC source/candidates; no learned or real event claims."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path


def _existing_cases():
    path = Path(__file__).resolve().parents[1] / "ui_declared_source_v1/cases.py"
    spec = importlib.util.spec_from_file_location("ui_dcec_existing_ec", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cases()


def descriptor(*, formula="B(Operator,O(Happens(Close,Tick12)))", fluent=False):
    from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_dcec_logic as owner
    return {"schema": owner.DESCRIPTOR_SCHEMA,
        "agents": [{"symbol": "Operator", "actor_id": "user", "source_ref_ids": ["source"]}],
        "events": [] if fluent else [{"symbol": "Close", "transition_id": "close", "event_id": "close_event", "source_ref_ids": ["source"]}],
        "fluents": [{"symbol": "Open", "state_id": "open", "source_ref_ids": ["source"]}] if fluent else [],
        "times": [{"symbol": "Tick14" if fluent else "Tick12", "clock_time": 14 if fluent else 12}],
        "formulas": [{"formula_id": "explicit-policy", "formula": formula, "source_ref_ids": ["source"]}]}


def _reserialize(row):
    source = json.loads(row["source_text"])
    source["candidate"] = deepcopy(row["candidate"])
    row["source_text"] = json.dumps(source, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return row


def base_case(identity="ui-dcec-belief-obligation-known-event", *, declaration=None, base_index=1):
    old = _existing_cases()[base_index]
    source = json.loads(old["source_text"])
    document = deepcopy(old["candidate"]["document"])
    # These source references are additional explicit authored declarations.
    # They are included in both complete source and candidate, not inferred.
    for native in document["events"] + document["states"]:
        native["source_ref_ids"] = ["source"]
    candidate = {"kind": "ui_declared_logic", "document": document,
        "logic": {"temporal": None, "tdfol": None, "dcec": declaration or descriptor()}}
    compound = {"schema": "ui-declared-logic-source/v1", "candidate": candidate,
                "interpretations": source["interpretations"]}
    return {"id": identity, "domain": "ui_ux_ir", "candidate": candidate,
        "source_text": json.dumps(compound, sort_keys=True, separators=(",", ":"), allow_nan=False),
        "candidate_origin": "authored_explicit_UI_DCEC_declaration_not_model_output",
        "model_inference_executed": False, "options": {}, "expected_disposition": "prepared"}


def cases():
    rows = [base_case(),
        base_case("ui-dcec-knowledge-prohibition-known-false-fluent",
            declaration=descriptor(formula="K(Operator,F(HoldsAt(Open,Tick14)))", fluent=True)),
        base_case("ui-dcec-intention-permission-known-false-event",
            declaration=descriptor(formula="I(Operator,P(not(Happens(Close,Tick12))))"), base_index=0)]
    rows.append(base_case("ui-dcec-belief-about-known-false-event", base_index=0))
    boundary = descriptor(formula="B(Operator,O(HoldsAt(Open,Tick14)))", fluent=True)
    boundary["times"][0]["clock_time"] = 16
    rows.append(base_case("ui-dcec-known-final-successor-fluent", declaration=boundary))
    changes = [
        ("unknown-event-boundary", "known prefix", lambda d: d["times"][0].update(clock_time=16)),
        ("role-collision", "noncolliding", lambda d: d["events"][0].update(symbol="Operator")),
        ("unknown-event-binding", "exact native transition", lambda d: d["events"][0].update(event_id="unrecorded")),
        ("unknown-agent", "wrong-role", lambda d: d["formulas"][0].update(formula="B(Other,O(Happens(Close,Tick12)))")),
        ("missing-normative-force", "require actual cognition", lambda d: d["formulas"][0].update(formula="B(Operator,Happens(Close,Tick12))")),
        ("wrong-source-reference", "known UI source", lambda d: d["agents"][0].update(source_ref_ids=["foreign"])),
    ]
    for name, reason, mutate in changes:
        row = deepcopy(rows[0])
        row.update(id="ui-dcec-" + name + "-blocked", expected_disposition="blocked", expected_reason=reason)
        mutate(row["candidate"]["logic"]["dcec"])
        rows.append(_reserialize(row))
    wrong = deepcopy(rows[0])
    wrong.update(id="ui-dcec-original-modal-prediction-mismatch-blocked", expected_disposition="blocked",
                 expected_reason="source_disagreement")
    wrong["candidate"]["logic"]["dcec"]["formulas"][0]["formula"] = "B(Operator,P(Happens(Close,Tick12)))"
    rows.append(wrong)
    false_guard = base_case("ui-dcec-positive-event-under-false-guard-blocked", base_index=4)
    false_guard.update(expected_disposition="blocked", expected_reason="false guard or wrong source")
    rows.append(false_guard)
    unknown_fluent = deepcopy(rows[4])
    unknown_fluent.update(id="ui-dcec-unknown-fluent-after-successor-blocked", expected_disposition="blocked",
                          expected_reason="known prefix")
    unknown_fluent["candidate"]["logic"]["dcec"]["times"][0]["clock_time"] = 18
    rows.append(_reserialize(unknown_fluent))
    return rows


def prepare_case(row):
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_logic_source as owner
    return owner.prepare_family_targets(row["source_text"], row["candidate"])
