"""Source-span argument custody over the existing live native4096 capability.

The verified-source owner retains exact source, producer, token and completed
operation evidence. The original span owner retains declared engineering target,
exposure and split policy. This bridge starts no native work and does not enable
the existing 4096 numerical owner's blocked training or real inference routes.
A receipt is ordinary evidence; it cannot replace either live capability.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from . import legal_span_consumer_binding as base
from . import legal_span_formula as span
from ...logic.formalization.autoencoder import source_embeddings_4096_verified as native

SCHEMA = "source-span-live-native4096-binding/v1"
PROFILE = "live-native4096-declared-engineering-supervision/v1"
Native4096SpanBindingError = base.SourceSpanConsumerBindingError
_RECEIVE = native.receive_verified_source_embeddings
_READ = native.read_verified_source_embeddings
_PINS = tuple((Path(module.__file__), hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
              for module in (base, native))
_SELF_PATH = Path(__file__)
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()


def _require(condition, message, *, receipt=None):
    if not condition:
        raise Native4096SpanBindingError(message, receipt=receipt)


def _implementation():
    for path, expected in ((_SELF_PATH, _SELF_SHA), *_PINS):
        _require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                 "native4096 span binding source changed since import")
    _require(native.receive_verified_source_embeddings is _RECEIVE
             and native.read_verified_source_embeddings is _READ,
             "native4096 verified owner callable changed")
    return {"binding_sha256": _SELF_SHA, "consumer": base._implementation(span),
            "verified_source_sha256": _PINS[1][1]}


def _receive(result, sources, producer):
    try:
        return _RECEIVE(result, rows=sources, expected_producer=producer)
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError) as error:
        raise Native4096SpanBindingError("native4096 source receiving failed: " + str(error)) from error


def _read(handle):
    try:
        return json.loads(base._preflight(_READ(handle)))
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError) as error:
        raise Native4096SpanBindingError("native4096 capability replay failed: " + str(error)) from error


def _arguments(split_manifest, eligibility_records, exposure_records):
    return dict(split_manifest=split_manifest, eligibility_records=eligibility_records,
                exposure_records=exposure_records)


@dataclass(frozen=True, slots=True, init=False)
class Native4096SpanBinding:
    """Nonserializable binding retaining the original verified live operation."""
    _base_binding: base.SourceSpanConsumerBinding
    _native_result: object
    _verified_native: native.VerifiedSourceEmbeddings4096
    _producer_guard: object
    _native_guard: object
    _implementation_guard: object
    _numerical_guard: object
    _numerical_json: bytes
    _receipt_json: bytes

    def __init__(self):
        raise TypeError("use prepare_native4096_span_binding")

    def __reduce__(self):
        raise TypeError("native4096 span binding is not serializable")

    def receipt(self):
        """Detached historical evidence; it cannot issue or restore a binding."""
        return json.loads(self._receipt_json)


def prepare_native4096_span_binding(rows, *, expected_rows_sha256, split_manifest,
        expected_split_manifest_sha256, eligibility_records, expected_eligibility_sha256,
        exposure_records, expected_exposure_sha256, operation, native_result,
        expected_producer, expected_producer_sha256, expected_native_receipt_sha256):
    """Bind the entire operation's ordered sources to declared engineering rows.

    Producer and row pins use canonical content hashing. The native receipt pin
    uses the original owner's canonical JSON plus trailing newline file recipe.
    No caller vector, row subset, saved receipt or alternative source is accepted.
    Native output width 4096 and span decoder token limits remain distinct.
    """
    implementation = base._guard(_implementation())
    base._sha256(expected_producer_sha256, "expected native producer SHA256")
    base._sha256(expected_native_receipt_sha256, "expected native receipt file SHA256")
    _require(type(rows) is list and 1 <= len(rows) <= native.MAX_ROWS,
             "complete native operation requires one through 128 source rows")
    producer = json.loads(base._preflight(expected_producer))
    producer_guard = base._guard(producer, expected_producer_sha256)
    arguments = _arguments(split_manifest, eligibility_records, exposure_records)
    original = base.prepare_source_span_consumer_binding(rows,
        expected_rows_sha256=expected_rows_sha256,
        expected_split_manifest_sha256=expected_split_manifest_sha256,
        expected_eligibility_sha256=expected_eligibility_sha256,
        expected_exposure_sha256=expected_exposure_sha256, operation=operation, **arguments)
    original_rows = json.loads(original._rows_json)
    sources = [{"id": row["id"], "source_text": row["source_text"]} for row in original_rows]
    handle = _receive(native_result, sources, producer)
    observed = _read(handle)
    _require(observed["native_provenance"]["receipt_sha256"] == expected_native_receipt_sha256,
             "native4096 original receipt pin differs")
    native_guard = base._guard(observed)
    contexts = [{"id": row["id"], "source_sha256": row["source_sha256"], "context": row["embedding"]}
                for row in observed["rows"]]
    numerical = [{**row, "latent": context["context"]} for row, context in zip(original_rows, contexts)]
    numerical_guard = base._guard(numerical)
    receipt = original.receipt()
    if receipt["status"] == "ready":
        try:
            span._records(numerical, native.DIMENSION)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
            raise Native4096SpanBindingError("native4096 numerical row contract differs: " + str(error)) from error
    base._check(numerical_guard, numerical, "prepared native4096 numerical rows")
    contract = dict(dimension=native.DIMENSION, representation_id=producer["profile"],
                    producer_sha256=producer_guard.sha256, training_index_sha256=base._guard(contexts).sha256)
    receipt.update(schema=SCHEMA, profile=PROFILE, source_binding_schema=base.SCHEMA,
        latent_dimension=native.DIMENSION, dimension_role="source_input_representation_width",
        context_stage="native4096", context_contract=contract,
        context_contract_scope="this_batch_only_not_an_automatically_selected_training_lineage",
        native_receipt_sha256=expected_native_receipt_sha256,
        native_receipt_digest_recipe="native_owner_canonical_JSON_plus_trailing_newline_file_SHA256",
        native_source_receipt=observed,
        numerical_rows_sha256=numerical_guard.sha256,
        strict_dimensional_records_check_passed=receipt["status"] == "ready",
        capability_checked=True, capability_scope="same_owner_process_and_native_thread_completed_operation",
        ordinary_receipt_is_capability=False, numerical_consumer_supported=False,
        native_training_enabled=False, encoder_executed_here=False,
        context_computation_reexecuted=False, resource_admission_granted=False,
        statutory_review_replayed=False,
        receipt_scope="engineering_input_custody_and_live_completed_native_source_capability",
        context_implementation=_implementation())
    receipt_raw = base._preflight(receipt)
    numerical_raw = base._preflight(numerical)
    base._check(numerical_guard, json.loads(numerical_raw), "serialized native4096 numerical rows")
    # Check the actual handle and every original input after all delegated work.
    base._check(native_guard, _read(handle), "completed native source observation")
    base.validate_source_span_consumer_binding(original, rows, **arguments)
    base._check(producer_guard, expected_producer, "original native producer")
    base._check(producer_guard, producer, "detached native producer")
    base._check(implementation, _implementation(), "native4096 binding implementation")
    base._check(numerical_guard, numerical, "final native4096 numerical rows")
    binding = object.__new__(Native4096SpanBinding)
    for key, value in dict(_base_binding=original, _native_result=native_result,
            _verified_native=handle, _producer_guard=producer_guard,
            _native_guard=native_guard, _implementation_guard=implementation,
            _numerical_guard=numerical_guard, _numerical_json=numerical_raw,
            _receipt_json=receipt_raw).items():
        object.__setattr__(binding, key, value)
    return binding


def validate_native4096_span_binding(binding, rows, *, split_manifest, eligibility_records,
        exposure_records, native_result, expected_producer):
    """Recheck originals and the actual completed handle before every use."""
    _require(type(binding) is Native4096SpanBinding, "prepared Native4096SpanBinding required")
    _require(native_result is binding._native_result, "original native operation handle required")
    arguments = _arguments(split_manifest, eligibility_records, exposure_records)
    base.validate_source_span_consumer_binding(binding._base_binding, rows, **arguments)
    base._preflight(expected_producer)
    base._check(binding._producer_guard, expected_producer, "native producer")
    base._check(binding._implementation_guard, _implementation(), "native4096 binding implementation")
    base._check(binding._native_guard, _read(binding._verified_native), "completed native source observation")
    # Read may call the original live owner; never dispatch under inputs that
    # changed during that boundary, even if their earlier checks succeeded.
    base.validate_source_span_consumer_binding(binding._base_binding, rows, **arguments)
    base._check(binding._producer_guard, expected_producer, "native producer after replay")
    base._check(binding._implementation_guard, _implementation(), "native4096 binding implementation")
    return binding.receipt()


def consume_native4096_span_binding(binding, rows, *, split_manifest, eligibility_records,
        exposure_records, native_result, expected_producer, consumer):
    """One callback on detached full numerical rows; no retry or fit permission.

    Callers must independently own their consumer's execution/resource policy.
    Existing 4096 numerical training and real-inference refusals remain effective.
    """
    receipt = validate_native4096_span_binding(binding, rows, split_manifest=split_manifest,
        eligibility_records=eligibility_records, exposure_records=exposure_records,
        native_result=native_result, expected_producer=expected_producer)
    _require(receipt["status"] == "ready", "native4096 source-span batch is blocked", receipt=receipt)
    _require(callable(consumer), "explicit callable consumer required")
    numerical = json.loads(binding._numerical_json)
    base._check(binding._numerical_guard, numerical, "detached native4096 numerical rows")
    return consumer(numerical)


__all__ = ["Native4096SpanBinding", "Native4096SpanBindingError", "SCHEMA", "PROFILE",
    "prepare_native4096_span_binding", "validate_native4096_span_binding", "consume_native4096_span_binding"]
