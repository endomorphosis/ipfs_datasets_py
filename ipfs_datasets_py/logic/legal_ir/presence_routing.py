"""Opt-in experimental composition of already saved source-span scores.

Selected optional-presence logits come from a source-identical parent; every
other value comes from the adapted occurrence. No model, target, training or
inference threshold is consulted. Borrowing a parent's decisions preserves its
errors too. Composition establishes no legal meaning or default decoder policy.
"""
from __future__ import annotations

import copy
import hashlib
import struct

from . import joint_span_selection as joint

SCHEMA = "saved-presence-score-routing/v1"
_OCCURRENCE_FIELDS = {"id", "source_sha256", "scores"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(joint._raw(value)).hexdigest()


def _binary32_digest(vector):
    # Inputs have passed the unchanged exact-float32 validator. Packing retains
    # signed zero, which ordinary equality does not distinguish.
    return hashlib.sha256(b"".join(struct.pack("!f", value) for value in vector)).hexdigest()


def _occurrence(source_text, value, name):
    _require(type(value) is dict and set(value) == _OCCURRENCE_FIELDS,
             name + " occurrence fields differ")
    _require(type(value["id"]) is str and bool(value["id"].strip()),
             name + " occurrence id must be nonempty text")
    expected = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    _require(type(value["source_sha256"]) is str and value["source_sha256"] == expected,
             name + " occurrence source SHA256 differs")
    return joint._validated(source_text, value["scores"])


def compose_presence_scores(source_text, parent_occurrence, adapted_occurrence, *, fields=("temporal",)):
    """Return ``{schema, occurrence, provenance}`` without changing either input.

    ``fields`` is a nonempty tuple of unique optional facets in canonical
    object/conditions/exceptions/temporal order. Required actor/action have no
    presence head and cannot be routed. Both complete saved score packets pass
    the unchanged joint selector's validator before any composition occurs.

    The returned occurrence retains the adapted ID, tokens, modality, all span
    boundaries, and every unrouted presence value. Selected vectors are copied
    verbatim from the parent, including signed zero. Provenance is detached from
    both inputs and from the returned score arrays. This is a saved-score
    experiment, never an actual owner report, trained checkpoint or semantic
    qualification; the caller must separately run and report its chosen readout.
    Score/ID/source validation does not authenticate any model or checkpoint
    producer. Immutable capture and checkpoint provenance remain the caller's
    responsibility.
    """
    _require(type(source_text) is str and bool(source_text.strip()),
             "source_text must be nonempty text")
    _require(type(fields) is tuple and bool(fields) and all(type(field) is str for field in fields)
             and fields == tuple(field for field in joint.OPTIONAL_FIELDS if field in fields),
             "fields must be unique optional facets in canonical order")
    parent = _occurrence(source_text, parent_occurrence, "parent")
    adapted = _occurrence(source_text, adapted_occurrence, "adapted")
    _require(parent_occurrence["id"] == adapted_occurrence["id"],
             "parent/adapted occurrence id differs")
    _require(joint._raw(parent["tokens"]) == joint._raw(adapted["tokens"]),
             "parent/adapted exact source tokens differ")

    occurrence = copy.deepcopy(adapted_occurrence)
    components = {}
    for field in fields:
        original = parent_occurrence["scores"]["presence_logits"][field]
        occurrence["scores"]["presence_logits"][field] = copy.deepcopy(original)
        components[field] = {}
        for role, vector in (("parent", original),
                             ("adapted", adapted_occurrence["scores"]["presence_logits"][field]),
                             ("composed", occurrence["scores"]["presence_logits"][field])):
            components[field][role] = {"logits": copy.deepcopy(vector),
                                       "binary32_sha256": _binary32_digest(vector)}
    provenance = {
        "origin": "experimental_saved_score_presence_routing", "id": occurrence["id"],
        "source_sha256": occurrence["source_sha256"], "routed_fields": list(fields),
        "parent_occurrence_sha256": _digest(parent_occurrence),
        "adapted_occurrence_sha256": _digest(adapted_occurrence),
        "composed_occurrence_sha256": _digest(occurrence),
        "presence_components": components, "binary32_encoding": "IEEE754_big_endian_preserving_signed_zero",
        "unchanged_adapted_components": ["tokens", "modality_logits", "start_logits", "end_logits", "unrouted_presence_logits"],
        "actual_owner_report": False, "trained_model": False, "model_checkpoint": None,
        "authority_scope": "composition operation only; caller must authenticate score/model provenance",
        "raw_output_repaired": False, "latent_semantics_tested": False,
        "independent_statutory_gold": False, "semantic_accuracy": None,
        "limitations": ["Parent presence errors and ambiguous ties are preserved; routing need not improve full IR agreement.",
                        "This detached saved-score composition establishes no legal-semantic qualification or default decoder policy."],
        **joint.FALSE,
    }
    return {"schema": SCHEMA, "occurrence": occurrence, "provenance": provenance}
