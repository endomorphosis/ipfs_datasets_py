"""Complete predeclared UI modal panel, including every negative case."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path


def _load(name):
    path = Path(__file__).with_name(name + "_cases.py")
    spec = importlib.util.spec_from_file_location("ui_modal_panel_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cases():
    temporal, dcec = _load("temporal"), _load("dcec")
    rows = temporal.cases() + dcec.cases()
    complete = dcec.base_case("ui-combined-state-norm-cognition-event")
    declared = temporal.descriptors(complete)
    declared["dcec"] = deepcopy(complete["candidate"]["logic"]["dcec"])
    complete["candidate"]["logic"] = declared
    source = json.loads(complete["source_text"])
    source["candidate"] = deepcopy(complete["candidate"])
    complete["source_text"] = json.dumps(source, sort_keys=True, separators=(",", ":"), allow_nan=False)
    complete["candidate_origin"] = "authored_compound_UI_modal_declaration_not_model_output"
    complete["expected_reason"] = None
    rows.append(complete)
    return rows


def prepare_case(row):
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_logic_source as owner
    return owner.prepare_family_targets(row["source_text"], row["candidate"])
