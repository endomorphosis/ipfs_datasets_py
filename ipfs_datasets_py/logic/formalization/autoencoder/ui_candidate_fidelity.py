"""Post-inference source agreement for an unchanged learned UI component.

Only the complete authored four-field sentence pair is recognized. This is a
bounded diagnostic reference, never a model input, repair, or natural-language
qualification. Native validity alone does not establish source agreement.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import sys

from ...autoformal import tree_pin
from . import intent_candidate_fidelity as json_audit
from . import ui_source_contract_384 as native_owner

SCHEMA = "ui-candidate-source-fidelity/v1"
MAX_BYTES = json_audit.MAX_BYTES
MAX_NODES = json_audit.MAX_NODES
MAX_DEPTH = json_audit.MAX_DEPTH
FALSE = {**json_audit.FALSE}


def _parse_source(source_text):
    """Recognize all four explicit fields, with no inferred/default values."""
    # No wildcard suffix, case folding, Unicode identifiers, or partial match:
    # additional claims and paraphrases must remain unsupported.
    match = re.fullmatch(
        r"[ \t\r\n]*Component[ \t\r\n]+(?P<component_id>[A-Za-z_][A-Za-z0-9_-]{0,255})"
        r"[ \t\r\n]+has[ \t\r\n]+role[ \t\r\n]+(?P<role>[A-Za-z_][A-Za-z0-9_-]{0,63})\."
        r"[ \t\r\n]+Its[ \t\r\n]+privacy[ \t\r\n]+sensitivity[ \t\r\n]+is"
        r"[ \t\r\n]+(?P<privacy_sensitivity>[A-Za-z_][A-Za-z0-9_-]{0,63})"
        r"[ \t\r\n]+and[ \t\r\n]+its[ \t\r\n]+presentation[ \t\r\n]+classification"
        r"[ \t\r\n]+is[ \t\r\n]+(?P<presentation_classification>[A-Za-z_][A-Za-z0-9_-]{0,63})"
        r"\.[ \t\r\n]*", source_text)
    if match is None:
        raise ValueError("source is outside the complete authored four-field UI grammar")
    reference = {"kind": "ui_component", "document": match.groupdict()}
    # The existing semantic owner determines closed vocabularies. The compared
    # reference remains the four explicitly captured values, not its defaults.
    native_owner.validate_training_target(reference)
    return reference


def _pins():
    from ....optimizers.logic_theorem_optimizer import autoencoder_schema_lake as owner_pin
    from ....optimizers.logic_theorem_optimizer import domain_384_autoencoder
    from ...ui_ux_ir import decoder, schema
    from ...ui_ux_ir.model import components

    root = Path(__file__).resolve().parents[4]
    if Path(tree_pin.workspace_root()).resolve() != root:
        raise ValueError("UI fidelity tree pin differs from selected source tree")
    modules = (sys.modules[__name__], json_audit, native_owner,
               domain_384_autoencoder, decoder, schema, components, tree_pin, owner_pin)
    if any(root not in Path(module.__file__).resolve().parents for module in modules):
        raise ValueError("UI fidelity owner resolved outside selected source tree")
    return {module.__name__: owner_pin._pin_imported_module(module) for module in modules}


def audit_ui_candidate(source_text, candidate):
    """Compare a target-free prediction with its complete supported source.

    Call only after model inference. ``candidate`` is the original
    ``{kind: ui_component, document: ...}`` envelope. Bounded malformed JSON is
    retained as native-invalid. Missing or additional candidate fields remain
    differences, including native optional fields; this API never fills them.
    No checkpoint, gold target, model, prover, or source repair is accepted.
    """
    if type(source_text) is not str or len(source_text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("bounded original source string required")
    candidate_bytes = json_audit._json_input(candidate)
    original = deepcopy(candidate)
    pins = _pins()
    resolved_tree = tree_pin.require_workspace_logic_tree()
    native_error = source_error = None
    try:
        if (type(original) is not dict or set(original) != {"kind", "document"}
                or original["kind"] != "ui_component"):
            raise ValueError("closed ui_component candidate envelope required")
        native_owner.validate_training_target(original)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        native_error = str(error)
    reference = None
    try:
        reference = _parse_source(source_text)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        source_error = str(error)
    differences = None if reference is None else json_audit._differences(reference, original)
    exact = native_error is None and source_error is None and not differences
    status = ("native_invalid" if native_error is not None else
              "source_unsupported" if source_error is not None else
              "source_agreement" if exact else "source_disagreement")
    report = {"schema": SCHEMA, "domain_id": "ui_ux_ir", "status": status,
        "source_text": source_text, "source_sha256": json_audit._sha(source_text.encode("utf-8")),
        "candidate": original, "candidate_sha256": json_audit._sha(candidate_bytes),
        "native_valid": native_error is None, "native_error": native_error,
        "native_validation_scope": "local_UI_component_fragment_and_closed_semantic_vocabulary",
        "source_supported": source_error is None, "source_error": source_error,
        "source_reference": reference,
        "source_reference_scope": "post_inference_bounded_whole_input_grammar_not_gold_semantics",
        "source_grammar": "authored_component_role_privacy_presentation_sentence_pair/v1",
        "exact": exact, "source_agreement": exact, "differences": differences,
        "comparison_scope": "complete_typed_candidate_envelope_and_UI_component_fields",
        "producer_pins": pins, "resolved_logic_tree": resolved_tree,
        "owner_pin_scope": "direct_owners_loaded_code_and_disk_not_transitive_callgraph",
        "model_inference_executed": False, "model_inputs_modified": False, **FALSE}
    if pins != _pins():
        raise ValueError("UI fidelity producer changed during audit")
    if json_audit._raw(original) != candidate_bytes or json_audit._json_input(candidate) != candidate_bytes:
        raise ValueError("UI fidelity candidate changed during audit")
    report["report_sha256"] = json_audit._sha(json_audit._raw(report))
    return report


__all__ = ["SCHEMA", "audit_ui_candidate"]
