"""Declared signed UI tick fixtures; no authenticated executions or training."""
from copy import deepcopy
import importlib.util
from pathlib import Path


def cases():
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v5 as adapter
    from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_bounded_event_calculus as owner
    from ipfs_datasets_py.logic.software_verification.trace import Clock, TimeValue, TimePoint, Event, TraceIR, ObservationPolicy
    path = Path(__file__).resolve().parents[1] / "native_dcec_ui_v1/guard_cases.py"
    spec = importlib.util.spec_from_file_location("base_ui_guard_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    guards = module.cases()

    def build(identity, signs, base_index=0, selfloop=False, extra_clock=False):
        row = deepcopy(guards[base_index])
        row["id"] = identity
        if selfloop:
            row["candidate"]["document"]["transitions"][0]["target_state_id"] = "open"
            behavior = row["options"]["behavior_interpretation"].to_dict()
            behavior["candidate_sha256"] = owner.digest(row["candidate"])
            behavior["behavior_model"]["transitions"][0]["target_state_id"] = "open"
            row["options"]["behavior_interpretation"] = adapter.UIBehaviorInterpretation.from_dict(behavior)
            guard = row["options"]["guard_interpretation"].to_dict()
            guard["candidate_sha256"] = owner.digest(row["candidate"])
            guard["behavior_sha256"] = owner.digest(behavior)
            row["options"]["guard_interpretation"] = adapter.UIGuardInterpretation.from_dict(guard)
        clocks = (Clock("clock:fixture", domain="discrete", unit="logical_tick", resolution=TimeValue(2),
            epoch="explicit-fixture-epoch"),)
        if extra_clock:
            clocks += (Clock("clock:other", domain="discrete", unit="second", resolution=TimeValue(1), epoch="other"),)
        atom = owner.occurrence_key("close")
        events = tuple(Event("observation:" + str(i), "ui_signed_tick", TimePoint("clock:fixture", TimeValue(10 + 2*i)),
            propositions=(atom,) if sign is True else (), false_propositions=(atom,) if sign is False else (),
            source_ref_ids=("source",)) for i, sign in enumerate(signs))
        native = TraceIR(clocks=clocks, events=events, kind="finite_prefix", primary_clock_id="clock:fixture",
            observation_policy=ObservationPolicy("policy:all-explicit", kind="explicit"))
        declaration = {"schema": owner.EVIDENCE_SCHEMA,
            "source_sha256": owner.guards.ui.previous._source(row["source_text"]),
            "candidate_sha256": owner.digest(row["candidate"]),
            "behavior_sha256": owner.digest(row["options"]["behavior_interpretation"].to_dict()),
            "guard_sha256": owner.digest(row["options"]["guard_interpretation"].to_dict()),
            "policy": deepcopy(owner.POLICY), "origin": 10, "initial_true_fluents": ["open"], "trace": native.to_dict()}
        row["options"]["event_interpretation"] = adapter.UIBoundedECInterpretation.from_dict(declaration)
        return row

    return [build("ui-ec-idle-inertia", [False, False, False]),
        build("ui-ec-occurrence-then-inertia", [False, True, False]),
        build("ui-ec-false-guard-idle", [False, False], base_index=1),
        build("ui-ec-unknown-occurrence-blocked", [False, None]),
        build("ui-ec-false-guard-occurrence-blocked", [True], base_index=1),
        build("ui-ec-wrong-source-occurrence-blocked", [True, True]),
        build("ui-ec-self-loop-blocked", [True], selfloop=True),
        build("ui-ec-conflicting-clocks-blocked", [False], extra_clock=True),
        build("ui-ec-timeout-still-blocked", [False], base_index=3)]
