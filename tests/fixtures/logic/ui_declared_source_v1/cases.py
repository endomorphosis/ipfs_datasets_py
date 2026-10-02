"""Authored complete UI declarations; not learned outputs or fresh holdouts.

Existing explicit document/model/guard/trace fixtures are repackaged as original
structured source. Only binding hashes are omitted from semantic bodies; old
UISourceRef provenance remains intact. No missing meaning is inferred.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path


def cases():
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_source_fidelity as api
    path = Path(__file__).resolve().parents[1] / "ui_bounded_event_v1/cases.py"
    spec = importlib.util.spec_from_file_location("ui_declared_existing_ec_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    excluded = {"source_sha256", "candidate_sha256", "behavior_sha256", "guard_sha256"}
    result = []
    for index, old in enumerate(module.cases()):
        bodies = {name: {k: deepcopy(v) for k, v in old["options"][name + "_interpretation"].to_dict().items()
                         if k not in excluded} for name in ("behavior", "guard", "event")}
        source = {"schema": api.SOURCE_SCHEMA, "document": deepcopy(old["candidate"]["document"]),
                  "interpretations": bodies}
        result.append({"id": "declared-" + old["id"], "domain": "ui_ux_ir",
            "source_text": json.dumps(source, sort_keys=True, separators=(",", ":"), allow_nan=False),
            "candidate": deepcopy(old["candidate"]), "candidate_origin": "authored_declared_source_fixture_not_model_output",
            "model_inference_executed": False, "previous_declared_source_text": old["source_text"], "options": {},
            "expected_disposition": "prepared" if index < 3 else "blocked",
            "expected_reason": None if index < 3 else ["unknown or extra", "false guard or wrong source",
                "false guard or wrong source", "self-loop", "one explicit clock", "clock semantics"][index - 3]})
    wrong = deepcopy(result[0])
    wrong.update(id="declared-ui-wrong-document-blocked", expected_disposition="blocked",
                 expected_reason="source_disagreement")
    wrong["candidate"]["document"]["title"] = "Unstated replacement title"
    result.append(wrong)
    omitted = deepcopy(result[0])
    source = json.loads(omitted["source_text"])
    source["document"].pop("title")
    omitted.update(id="declared-ui-omitted-source-default-blocked", expected_disposition="blocked",
        expected_reason="source_unsupported", source_text=json.dumps(source, sort_keys=True, separators=(",", ":")))
    result.append(omitted)
    return result


def prepare_case(row):
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_source_fidelity as api
    return api.prepare_family_targets(row["source_text"], row["candidate"])
