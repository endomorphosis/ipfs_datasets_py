"""Opt-in cached replay of the two selected normative recipes at 384D/768D.

The checkpoint recipe, original codec and source packets are never rewritten.
The versioned decoder contract identifies this experimental replay API; it does
not fill the assets' null native IR schema/profile/format selectors. Preparation
has no model, manager, database or network action. Opening explicitly restores
the existing numerical model, with all qualification and proof flags false.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import contextual_legal_ir_runtime as contextual
from . import ir_model_manager_import as registration

SCHEMA = "normative-legal-ir-runtime-plan/v1"
DECODER_CONTRACT_ID = "normative-selected-cached-legal-ir/v1"
SOURCE_OWNER_NAMES = contextual.SOURCE_OWNER_NAMES + (
    "normative_legal_ir_runtime", "ir_model_manager_import")
MAX_REFERENCE_BYTES = contextual.MAX_REFERENCE_BYTES
NormativeLegalRuntimeError = contextual.ContextualLegalRuntimeError
_RECIPES = {"normative-wording-zero": {"name": "normative-wording-zero", "weight": 0.0},
            "normative-wording-ce": {"name": "normative-wording-ce", "weight": 0.05}}
_REQUEST_FIELDS = contextual._REQUEST_FIELDS | {"decoder_contract_id", "training_recipe_name"}
_VOCABULARY = ["<pad>", "<bos>", "<eos>", '"F"', '"O"', '"P"', '"action"',
    '"actor"', '"approve"', '"archive"', '"conditions"', '"deliver"', '"examine"',
    '"exceptions"', '"modality"', '"notary"', '"notice"', '"object"', '"preserve"',
    '"publish"', '"registrar"', '"rules"', '"secretary"', '"temporal"', '"treasurer"',
    '"trustee"', ",", ":", "[", "]", "{", "}"]


def _validate_request(request):
    contextual._require(type(request) is dict and set(request) == _REQUEST_FIELDS,
                        "closed seven-field normative request required")
    contextual._require(type(request["decoder_contract_id"]) is str
        and request["decoder_contract_id"] == DECODER_CONTRACT_ID,
        "exact opt-in normative decoder contract required")
    contextual._require(type(request["training_recipe_name"]) is str
        and request["training_recipe_name"] in _RECIPES, "explicit supported normative recipe required")


def _capture(request, *, source_owner_pins, **kwargs):
    _validate_request(request)
    contextual._require(type(source_owner_pins) is dict
        and set(source_owner_pins) == set(SOURCE_OWNER_NAMES), "exact fifteen-owner normative source closure required")
    legacy = {name: source_owner_pins[name] for name in contextual.SOURCE_OWNER_NAMES}
    options = contextual._capture(
        {key: request[key] for key in contextual._REQUEST_FIELDS}, source_owner_pins=legacy, **kwargs)
    for name in ("normative_legal_ir_runtime", "ir_model_manager_import"):
        pin = contextual._pin(source_owner_pins[name], 512 * 1024)
        contextual._require(pin["path"] == str(Path(__file__).with_name(name + ".py")),
                            "normative source owner must be the fixed current library file")
        options["pins"]["source:" + name] = pin
    contextual._require(sum(pin["bytes"] for pin in options["pins"].values()) <= contextual.MAX_TOTAL_BYTES,
                        "aggregate normative custody bytes exceed bound")
    options["normative_request"] = dict(request)
    return options


def _prepare(options):
    request = options["normative_request"]
    _validate_request(request)
    contextual._require(contextual._raw({key: request[key] for key in contextual._REQUEST_FIELDS})
        == contextual._raw(options["request"]), "normative and native request identities differ")
    recipe = _RECIPES[request["training_recipe_name"]]
    plan, prepared, witnesses = contextual._prepare(options, _selected_recipe=recipe)
    contextual._require(contextual._raw(prepared["checkpoint"]["codec"]) == contextual._raw({
        "schema": "typed-json-lexical/v1", "target_vocabulary": _VOCABULARY}),
        "exact inherited normative32 vocabulary and ordering required")
    contextual._verify_origins(plan)
    role = request["training_recipe_name"].replace("-", "_") + "_selected_semantic_decoder_state"
    selector = {key: request[key] for key in contextual._REQUEST_FIELDS}
    selector.update(record_id=registration.ir_model_asset_record_id(request["ir_family_id"],
        request["dimension"], request["dimension_role"], role, request["checkpoint_sha256"]),
        role=role, schema_version=None, profile_id=None, format_id=None)
    plan.update(schema=SCHEMA, request=dict(request), decoder_contract_id=DECODER_CONTRACT_ID,
        saved_training_recipe=dict(recipe), model_manager_selector=selector,
        model_manager_binding_resolved=False,
        decoder_contract=dict(schema="normative-cached-decoder-contract/v1",
            task_id="semantic_IR_reconstruction", state_role="selected",
            output_codec_schema="typed-json-lexical/v1", output_vocabulary_size=32,
            native_ir_schema_version=None, decoder_profile_id=None, decoder_format_id=None,
            cached_source_scope="original_saved_preprocessing_split_only",
            arbitrary_new_source_inputs_supported=False,
            original_text_reconstruction_supported=False))
    # The derived selector does not read or refresh the manager. Caller-pinned
    # source provenance retains the original contextual replay's limitations.
    contextual._fence(options["pins"], witnesses)
    contextual._verify_origins(plan)
    return json.loads(contextual._raw(plan)), prepared, witnesses


def prepare_normative_legal_ir_runtime(request, *, checkpoint_pin, preprocessing_pin,
        donor_checkpoint_pin, source_inputs_pin, source_contexts_pin, source_owner_pins,
        row_ids, deadline_seconds=120, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Authenticate one selected normative checkpoint and its original cached split."""
    try:
        options = _capture(request, checkpoint_pin=checkpoint_pin, preprocessing_pin=preprocessing_pin,
            donor_checkpoint_pin=donor_checkpoint_pin, source_inputs_pin=source_inputs_pin,
            source_contexts_pin=source_contexts_pin, source_owner_pins=source_owner_pins,
            row_ids=row_ids, deadline_seconds=deadline_seconds, max_reference_bytes=max_reference_bytes)
        return _prepare(options)[0]
    except (OSError, RuntimeError, OverflowError, TypeError, UnicodeError) as error:
        raise NormativeLegalRuntimeError("cannot prepare bounded normative replay: " + str(error)) from error


class _NormativeLegalAutoencoder(contextual._ContextualLegalAutoencoder):
    def describe(self):
        result = super().describe()
        plan = json.loads(self._plan_bytes)
        result.update(schema="normative-legal-ir-runtime-description/v1",
            decoder_contract=plan["decoder_contract"], decoder_contract_id=DECODER_CONTRACT_ID,
            saved_training_recipe=plan["saved_training_recipe"],
            model_manager_selector=plan["model_manager_selector"], model_manager_binding_resolved=False)
        return result

    def infer_cached(self):
        result = super().infer_cached()
        result["schema"] = "normative-legal-ir-cached-inference/v1"
        return result


def open_normative_legal_ir_autoencoder(request, *, checkpoint_pin, preprocessing_pin,
        donor_checkpoint_pin, source_inputs_pin, source_contexts_pin, source_owner_pins,
        row_ids, deadline_seconds=120, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Explicit lazy restoration after normative recipe/codec/custody validation."""
    started = returned = False
    try:
        options = _capture(request, checkpoint_pin=checkpoint_pin, preprocessing_pin=preprocessing_pin,
            donor_checkpoint_pin=donor_checkpoint_pin, source_inputs_pin=source_inputs_pin,
            source_contexts_pin=source_contexts_pin, source_owner_pins=source_owner_pins,
            row_ids=row_ids, deadline_seconds=deadline_seconds, max_reference_bytes=max_reference_bytes)
        plan, prepared, witnesses = _prepare(options)
        owner = contextual._numeric_owner(plan)
        contextual._fence(options["pins"], witnesses)
        started = True
        model = owner.restore_contextual_legal_model(json.loads(contextual._raw(prepared)))
        returned = True
        wrapped = _NormativeLegalAutoencoder(owner, model, options, plan, witnesses, _prepare_plan=_prepare)
        wrapped._recheck()
        return wrapped
    except Exception as error:
        refused = error if isinstance(error, NormativeLegalRuntimeError) else NormativeLegalRuntimeError(str(error))
        refused.model_load_started, refused.model_load_performed = started, returned
        if refused is error:
            raise
        raise refused from error


__all__ = ["SCHEMA", "DECODER_CONTRACT_ID", "SOURCE_OWNER_NAMES", "MAX_REFERENCE_BYTES",
           "NormativeLegalRuntimeError", "prepare_normative_legal_ir_runtime",
           "open_normative_legal_ir_autoencoder"]
