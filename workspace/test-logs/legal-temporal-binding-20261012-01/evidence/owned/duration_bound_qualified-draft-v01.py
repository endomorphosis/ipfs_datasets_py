"""Opt in to the unchanged qualified emitter after exact duration custody replay.

The structural report is a prerequisite, not semantic approval. No candidate,
interpretation, clock, scope or native output is repaired. This v1 consumer uses
the existing no-context qualified profile; context-bound transport remains inert
until a separate lowering profile owns context meaning. No model or backend runs.
"""
from __future__ import annotations

import hashlib
import importlib
from copy import deepcopy
from pathlib import Path

from . import temporal_bindings as bindings

SCHEMA = "duration-bound-canonical-qualified/v1"
VALIDATION_SCHEMA = "duration-bound-canonical-qualified-validation/v1"
PROFILE = "no-context-duration-custody-before-qualified-emission/v1"
FALSE = {key: value for key, value in bindings.FALSE.items() if key != "native_lowering_performed"}


def _owner():
    return importlib.import_module("ipfs_datasets_py.logic.autoformal.legal_canonical_qualified")


def producer_pins():
    """Retain existing and additive producer endpoint identities, not authority."""
    pins = dict(_owner().producer_pins())
    for module in (bindings, importlib.import_module("ipfs_datasets_py.logic.legal_ir.canonical_statement_scope")):
        path = Path(module.__file__).resolve()
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    path = Path(__file__).resolve()
    pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return pins


def prepare_duration_bound_qualified(report, candidate, interpretation, scope_request, scope_declaration,
                                      occurrence_bindings, clock_declarations, *, expected_report_sha256,
                                      expected_candidate_sha256, expected_interpretation_sha256,
                                      expected_scope_input_sha256, expected_scope_declaration_sha256):
    """Replay externally pinned custody before importing/calling a native owner.

    Native grammar, formula/mapping integrity and emitted code retain their old
    owner's checks. The new report is retained unchanged beside that owner's
    complete output. Neither transport nor Lean preparation admits legal targets.
    """
    retained = [bindings._detach(value) for value in (report, candidate, interpretation, scope_request,
                scope_declaration, occurrence_bindings, clock_declarations)]
    report, candidate, interpretation, request, declaration, maps, clocks = retained
    bindings._sha(expected_report_sha256, "externally expected duration report")
    bindings._require(bindings.digest(report) == expected_report_sha256, "externally expected duration report differs")
    expected = dict(expected_candidate_sha256=expected_candidate_sha256,
                    expected_interpretation_sha256=expected_interpretation_sha256,
                    expected_scope_input_sha256=expected_scope_input_sha256,
                    expected_scope_declaration_sha256=expected_scope_declaration_sha256)
    validation = bindings.validate_duration_bindings(report, candidate, interpretation, request, declaration,
                                                    maps, clocks, **expected)
    bindings._require(request["context"]["role"] == "none_required" and request["context"]["text"] == "",
                      "duration-bound qualified consumer requires none_required context; no context meaning is inferred")
    bindings._require(all(row["duration_anchor"]["origin"] == "source" and row["clock_anchor"]["origin"] == "source"
                         for row in report["joins"]), "qualified consumer requires exact direct source occurrences")
    # The first native owner import occurs only after all binding/context gates.
    owner = _owner()
    pins = producer_pins()
    native = owner.prepare_canonical_qualified(deepcopy(candidate), deepcopy(interpretation))
    bindings._require(native["candidate_sha256"] == expected_candidate_sha256
                      and native["interpretation_sha256"] == expected_interpretation_sha256
                      and native["interpretation"] == interpretation
                      and native["original_canonical_ir"] == candidate["canonical_ir"],
                      "unchanged native output candidate/interpretation differs")
    bindings._require(producer_pins() == pins, "duration-bound qualified producer endpoints changed")
    result = {"schema": SCHEMA, "profile": PROFILE, "status": "native_qualified_output_prepared_with_duration_custody",
              "binding_report": report, "binding_report_sha256": expected_report_sha256,
              "binding_validation": validation, "binding_validation_sha256": bindings.digest(validation),
              "native_output": bindings._detach(native), "native_output_sha256": bindings.digest(native),
              "native_output_preserved_exactly": True, "interpretation_preserved_exactly": True,
              "native_lowering_prepared": True, "native_lowering_performed": True,
              "lean_source_prepared": True, "backend_build_required": "lake build legal",
              "source_context_profile": "none_required_only", "producer_pins": pins,
              "duration_count": report["duration_count"], "masks": deepcopy(report["masks"]),
              "model_calls": 0, "prover_calls": 0, **FALSE}
    result["content_sha256"] = bindings.digest(result)
    bindings._wire(result)
    return result


def validate_duration_bound_qualified(output, report, candidate, interpretation, scope_request,
                                       scope_declaration, occurrence_bindings, clock_declarations, **expected_pins):
    """Replay exact original inputs and unchanged native output; no backend call."""
    output = bindings._detach(output)
    replay = prepare_duration_bound_qualified(report, candidate, interpretation, scope_request,
                                               scope_declaration, occurrence_bindings, clock_declarations, **expected_pins)
    bindings._require(bindings._wire(output) == bindings._wire(replay), "duration-bound native output differs from exact replay")
    result = {"schema": VALIDATION_SCHEMA, "status": "validated_duration_bound_native_preparation_only",
              "output_sha256": bindings.digest(output), "output_content_sha256": output["content_sha256"],
              "binding_report_sha256": output["binding_report_sha256"], "native_output_sha256": output["native_output_sha256"],
              "duration_count": output["duration_count"], "masks": deepcopy(output["masks"]),
              "model_calls": 0, "prover_calls": 0, **FALSE}
    result["content_sha256"] = bindings.digest(result)
    return result


__all__ = ["prepare_duration_bound_qualified", "validate_duration_bound_qualified", "producer_pins"]
