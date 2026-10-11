"""Opt-in candidate decoding of newly supplied source-bound native inputs.

This contract keeps the selected normative checkpoint, codec and transforms.
It admits new input occurrences through independently pinned native production
records rather than relabelling the retained 48-paragraph assay. Preparation
does not run an encoder or decoder. Numerical opening remains explicit and
lazy; generated candidates carry no statutory meaning or proof authority.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from . import arbitrary_native_source_cache as cache_owner
from . import contextual_legal_ir_runtime as contextual
from . import normative_legal_ir_runtime as normative

SCHEMA = "arbitrary-native-legal-ir-runtime-plan/v1"
DECODER_CONTRACT_ID = "arbitrary-native-source-cache-legal-ir/v1"
_EXTRA_AUTOENCODER = (
    "arbitrary_native_legal_ir_runtime", "arbitrary_native_source_cache",
    "legal_native_conditioning", "dimension_source_inputs",
    "source_embeddings_768", "source_embeddings_768_complete", "gte_multilingual_profile",
)
_EXTRA_OPTIMIZER = (
    "autoencoder_embedding_production", "autoencoder_embedding_runtime",
    "autoencoder_corpus_manifest", "autoencoder_training_worker",
)
SOURCE_OWNER_NAMES = normative.SOURCE_OWNER_NAMES + _EXTRA_AUTOENCODER + _EXTRA_OPTIMIZER
MAX_REFERENCE_BYTES = contextual.MAX_REFERENCE_BYTES
ArbitraryNativeLegalRuntimeError = contextual.ContextualLegalRuntimeError


def source_owner_paths():
    directory = Path(__file__).parent
    optimizer = directory.parents[2] / "optimizers" / "logic_theorem_optimizer"
    return {
        **{name: str(directory / (name + ".py")) for name in
           normative.SOURCE_OWNER_NAMES + _EXTRA_AUTOENCODER},
        **{name: str(optimizer / (name + ".py")) for name in _EXTRA_OPTIMIZER},
    }


def _verify_origins(options):
    for name, path in source_owner_paths().items():
        namespace = "ipfs_datasets_py.optimizers.logic_theorem_optimizer" if name in _EXTRA_OPTIMIZER else __package__
        module = sys.modules.get(namespace + "." + name)
        if module is not None:
            contextual._require(getattr(module, "__file__", None) == path,
                                "loaded arbitrary-native source owner origin differs")
    reference = sys.modules.get(__package__ + ".source_embeddings_768")
    if reference is not None:
        contextual._require(getattr(getattr(reference, "_PROFILE", None), "__file__", None) ==
                            source_owner_paths()["gte_multilingual_profile"],
                            "loaded arbitrary-native profile origin differs")


def _capture(request, *, checkpoint_pin, preprocessing_pin, donor_checkpoint_pin,
             source_cache_pin, source_requests_pin, native384_receipt_refs,
             native768_report_refs, source_artifact_pins, source_owner_pins,
             row_ids, deadline_seconds, max_reference_bytes):
    contextual._require(type(source_owner_pins) is dict and
                        set(source_owner_pins) == set(SOURCE_OWNER_NAMES),
                        "exact arbitrary-native source owner closure required")
    options = normative._capture(request, checkpoint_pin=checkpoint_pin,
        preprocessing_pin=preprocessing_pin, donor_checkpoint_pin=donor_checkpoint_pin,
        source_inputs_pin=source_cache_pin, source_contexts_pin=source_cache_pin,
        source_owner_pins={name: source_owner_pins[name] for name in normative.SOURCE_OWNER_NAMES},
        row_ids=row_ids, deadline_seconds=deadline_seconds, max_reference_bytes=max_reference_bytes,
        _decoder_contract_id=DECODER_CONTRACT_ID)
    for name in _EXTRA_AUTOENCODER + _EXTRA_OPTIMIZER:
        pin = contextual._pin(source_owner_pins[name], 512 * 1024)
        contextual._require(pin["path"] == source_owner_paths()[name],
                            "arbitrary-native owner must be the fixed current library file")
        options["pins"]["source:" + name] = pin
    options["pins"]["source_requests"] = contextual._pin(source_requests_pin, max_reference_bytes)
    dimension = request["dimension"]
    for name, refs in (("native384", native384_receipt_refs), ("native768", native768_report_refs)):
        refs = [] if refs is None else refs
        contextual._require(type(refs) in (list, tuple) and len(refs) <= 128,
                            "bounded explicit native production references required")
        contextual._require(bool(refs) == (dimension == int(name[6:])),
                            "only the requested native width may supply production records")
        options[name + "_refs"] = []
        for index, reference in enumerate(refs):
            pin = contextual._pin(reference, max_reference_bytes)
            contextual._require(pin not in options[name + "_refs"], "duplicate native production reference")
            options[name + "_refs"].append(pin)
            options["pins"][name + ":" + str(index)] = pin
    contextual._require(type(source_artifact_pins) is dict and 1 <= len(source_artifact_pins) <= 64,
                        "bounded exact source artifact pins required")
    options["source_artifact_pins"] = {}
    for digest, reference in source_artifact_pins.items():
        pin = contextual._pin(reference, max_reference_bytes)
        contextual._require(contextual._hash(digest) and digest == pin["sha256"],
                            "source artifact key must be its exact byte hash")
        options["source_artifact_pins"][digest] = pin
        # The contextual reader treats source-prefixed pins as opaque bytes.
        # Plain source documents must never be parsed as JSON or as targets.
        options["pins"]["source:artifact:" + digest] = pin
    contextual._require(sum(pin["bytes"] for pin in options["pins"].values()) <= contextual.MAX_TOTAL_BYTES,
                        "aggregate arbitrary-native custody bytes exceed bound")
    _verify_origins(options)
    return options


def _source_packet(documents, options, dimension):
    _verify_origins(options)
    cache = documents["source_inputs"]
    contextual._require(contextual._raw(cache) == contextual._raw(documents["source_contexts"]),
                        "arbitrary-native cache views differ")
    requests = documents["source_requests"]
    contextual._require(type(requests) is list and requests, "explicit source request rows required")
    requested_artifacts = {row["source"]["artifact"]["sha256"] for row in requests}
    contextual._require(requested_artifacts == set(options["source_artifact_pins"]),
                        "source artifact pin inventory must match requests exactly")

    def resolver(artifact):
        pin = options["source_artifact_pins"].get(artifact["sha256"])
        contextual._require(pin is not None and pin["bytes"] == artifact["bytes"],
                            "source resolver artifact identity differs")
        contextual._read(pin, retain=True)
        # Corpus/native producers own the verified byte read and require a
        # local path, rather than the already authenticated byte payload.
        return pin["path"]

    checked = cache_owner.validate_arbitrary_native_source_cache(cache,
        source_requests=requests, native384_receipt_refs=options["native384_refs"] or None,
        native768_report_refs=options["native768_refs"] or None, source_resolver=resolver)
    _verify_origins(options)
    contextual._require(checked["dimension"] == dimension, "arbitrary-native cache width differs")
    rows, contexts = checked["rows"], checked["source_contexts"]
    # Physical occurrences with identical prose remain distinct. Validate each
    # literal context independently rather than deduplicating source meanings.
    by_id = {}
    for index, row in enumerate(rows):
        identifier = row["id"]
        contextual._require(identifier not in by_id, "duplicate arbitrary-native occurrence ID")
        one = contextual._source_rows([row], {identifier: contexts[identifier]}, dimension, [identifier])
        by_id[identifier] = (index, one[identifier][1], one[identifier][2])
    contextual._require(all(identifier in by_id for identifier in options["row_ids"]),
                        "selected occurrence has a refused or missing native input")
    return contextual._selected_sources(by_id, options["row_ids"])


def _prepare(options):
    _verify_origins(options)
    plan, prepared, witnesses = normative._prepare(options,
        _decoder_contract_id=DECODER_CONTRACT_ID, _source_packet=_source_packet)
    artifact_receipts = {}
    for name in list(plan["source_owner_receipts"]):
        if name.startswith("artifact:"):
            artifact_receipts[name[9:]] = plan["source_owner_receipts"].pop(name)
    plan.update(schema=SCHEMA, source_artifact_receipts=artifact_receipts,
        source_cache_binding=dict(schema="arbitrary-native-source-cache-binding/v1",
            cache_schema=cache_owner.SCHEMA, source_requests_pin=options["pins"]["source_requests"],
            native_production_refs=options["native384_refs"] + options["native768_refs"],
            selected_occurrences=len(plan["source_inputs"]["rows"]),
            selected_clauses=sum(len(row["segments"]) for row in plan["source_inputs"]["contexts"].values()),
            physical_occurrence_identity_preserved=True, recorded_native_consistency_checked=True,
            encoder_execution_attested=False, source_authority_authenticated=False,
            target_representability_verified=False, statutory_semantics_verified=False))
    plan["decoder_contract"].update(cached_source_scope="explicit_new_source_occurrences_and_native_receipts",
        arbitrary_new_source_inputs_supported=True, legal_fidelity_qualified=False,
        target_representability_verified=False, output_scope="normative32_candidate_language")
    plan["input_contract"].update(paragraph_vector_binding="exact_source_span_and_native_production_record",
        clause_vector_binding="exact_literal_offsets_and_native_production_record",
        native_execution_record_consistency_checked=True, native_execution_attested=False)
    contextual._fence(options["pins"], witnesses)
    _verify_origins(options)
    return json.loads(contextual._raw(plan)), prepared, witnesses


def prepare_arbitrary_native_legal_ir_runtime(request, **options):
    """Check a new-source cache and selected checkpoint without model execution."""
    try:
        captured = _capture(request, deadline_seconds=options.pop("deadline_seconds", 120),
            max_reference_bytes=options.pop("max_reference_bytes", MAX_REFERENCE_BYTES), **options)
        return _prepare(captured)[0]
    except (OSError, RuntimeError, OverflowError, TypeError, UnicodeError, KeyError, ValueError) as error:
        refused = error if isinstance(error, ArbitraryNativeLegalRuntimeError) else ArbitraryNativeLegalRuntimeError(
            "cannot prepare arbitrary-native candidates: " + str(error))
        if hasattr(error, "disposition"):
            refused.source_cache_disposition = error.disposition
        if refused is error:
            raise
        raise refused from error


class _ArbitraryNativeLegalAutoencoder(normative._NormativeLegalAutoencoder):
    def describe(self):
        result = super().describe()
        plan = json.loads(self._plan_bytes)
        result.update(schema="arbitrary-native-legal-ir-description/v1",
            decoder_contract_id=DECODER_CONTRACT_ID,
            source_artifact_receipts=plan["source_artifact_receipts"],
            source_cache_binding=plan["source_cache_binding"])
        return result

    def infer_cached(self):
        result = super().infer_cached()
        result["schema"] = "arbitrary-native-legal-ir-candidate-inference/v1"
        return result


def open_arbitrary_native_legal_ir_autoencoder(request, **options):
    """Restore the selected normative state for explicitly unqualified candidates."""
    started = returned = False
    try:
        captured = _capture(request, deadline_seconds=options.pop("deadline_seconds", 120),
            max_reference_bytes=options.pop("max_reference_bytes", MAX_REFERENCE_BYTES), **options)
        plan, prepared, witnesses = _prepare(captured)
        owner = contextual._numeric_owner(plan)
        contextual._fence(captured["pins"], witnesses)
        _verify_origins(captured)
        started = True
        model = owner.restore_contextual_legal_model(json.loads(contextual._raw(prepared)))
        returned = True
        wrapped = _ArbitraryNativeLegalAutoencoder(owner, model, captured, plan, witnesses, _prepare_plan=_prepare)
        wrapped._recheck()
        return wrapped
    except Exception as error:
        refused = error if isinstance(error, ArbitraryNativeLegalRuntimeError) else ArbitraryNativeLegalRuntimeError(str(error))
        refused.model_load_started, refused.model_load_performed = started, returned
        if hasattr(error, "disposition"):
            refused.source_cache_disposition = error.disposition
        if refused is error:
            raise
        raise refused from error


__all__ = ["SCHEMA", "DECODER_CONTRACT_ID", "SOURCE_OWNER_NAMES", "MAX_REFERENCE_BYTES",
           "ArbitraryNativeLegalRuntimeError", "source_owner_paths",
           "prepare_arbitrary_native_legal_ir_runtime", "open_arbitrary_native_legal_ir_autoencoder"]
