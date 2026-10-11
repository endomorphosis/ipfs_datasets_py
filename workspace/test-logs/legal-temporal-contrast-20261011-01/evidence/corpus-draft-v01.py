"""Authored temporal-role contrasts for the copied-span decoder.

The fixed v1 corpus is fictional engineering data, never statutory gold.  The
positive and negative member of each pair differ only by the presence of an
explicitly authored normative duration.  Duration-looking text in an actor,
object, condition or exception remains in that field.  Character and UTF-8
coordinates are recorded while assembling segments; no occurrence is selected
by a first-match search.  Trainable normative and distractor literals differ.

The separate repeated-identical-literal panel records the existing label
owner's unsupported ambiguity.  Its occurrence map does not override that
owner and the panel is never exported for fitting.  Challenge references are
visible to this builder's author and are only generated engineering references.
All templates are shared authored grammar; no independent semantic review or
structural novelty is claimed.  This module imports only the standard library.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = "authored-temporal-role-contrast-corpus/v1"
ROW_SCHEMA = "authored-temporal-role-contrast-row/v1"
PROVENANCE = "fictional_authored_engineering_not_statutory_gold"
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
QUALIFIERS = FIELDS[3:]
MODALITIES = ("O", "P", "F")
CLASSES = (
    "plain_deadline", "condition_duration", "exception_duration",
    "actor_duration_name", "object_duration_title", "condition_exception_duration",
)
SPLITS = ("train", "tuning", "challenge")
EXPECTED_COUNTS = {"train": 72, "tuning": 36, "challenge": 36,
                   "ambiguous_diagnostics": 6}
LATENT_DIMENSION = 384
MAX_CORPUS_BYTES = 8 * 1024 * 1024
_CUES = {"O": "shall", "P": "may", "F": "shall not"}
_LEXICONS = {
    "train": (("Asterquay", "inspect", "register"),
              ("Birchmere", "archive", "filing packet")),
    "tuning": (("Cobaltfen", "retain", "notice"),),
    "challenge": (("Dahliaharbor", "submit", "ledger"),),
}
_SPLIT_BASE = {"train": 100, "tuning": 400, "challenge": 700}
_FALSE = {
    "semantic_gold": False, "independently_reviewed": False,
    "statutory_targets_created": False, "source_semantics_verified": False,
    "legal_fidelity_qualified": False, "family_qualified": False,
    "proof_authority": False, "Lake_executed": False,
    "training_executed": False, "model_execution_performed": False,
    "encoder_execution_performed": False, "default_promoted": False,
}


class TemporalContrastCorpusError(ValueError):
    """An altered corpus or an unsupported export was supplied."""


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Assembly:
    def __init__(self):
        self.parts = []
        self.characters = 0
        self.bytes = 0
        self.facets = {field: None for field in FIELDS}
        self.durations = []

    def _position(self):
        return self.characters, self.bytes

    def _span(self, start, text):
        return {"char_start": start[0], "char_end": self.characters,
                "utf8_byte_start": start[1], "utf8_byte_end": self.bytes,
                "text": text, "text_sha256": _sha(text)}

    def append(self, text):
        start = self._position()
        self.parts.append(text)
        self.characters += len(text)
        self.bytes += len(text.encode("utf-8"))
        return self._span(start, text)

    def facet(self, field, prefix, duration=None, suffix=""):
        start = self._position()
        self.append(prefix)
        if duration is not None:
            span = self.append(duration)
            self.durations.append({"role": field, "qualifier_index": 0 if field in QUALIFIERS else None,
                                   "normative": field == "temporal", "span": span})
        self.append(suffix)
        text = prefix + (duration or "") + suffix
        self.facets[field] = self._span(start, text)

    def source(self):
        return "".join(self.parts)


def _row(split, class_name, lexical_index, modality, temporal_present, *, ambiguous=False):
    class_index = CLASSES.index(class_name)
    if ambiguous:
        name, action, obj = ("Églantineprobe", "record", "register")
        base = 1000 + class_index * 10
        group = "temporal-contrast-ambiguous-" + class_name
    else:
        stem, action, obj = _LEXICONS[split][lexical_index]
        name = stem + str(class_index)
        base = _SPLIT_BASE[split] + lexical_index * 100 + class_index * 10
        group = "temporal-contrast-" + split + "-" + class_name + "-" + str(lexical_index)
    norm_duration = "within " + str(base + 1) + " days"
    distractor = norm_duration if ambiguous else "within " + str(base + 2) + " days"
    other_distractor = "within " + str(base + 3) + " days"
    pair = group + "-" + modality.lower()
    identifier = pair + ("-present" if temporal_present else "-absent")
    actor = "the " + name + " Office"
    obj = "the " + name.lower() + " " + obj
    has_condition = class_name in ("condition_duration", "condition_exception_duration")
    has_exception = class_name in ("exception_duration", "condition_exception_duration")
    condition_prefix = "the " + name.lower() + " application was received "
    condition_suffix = " of publication"
    exception_prefix = "the " + name.lower() + " waiver notice states “"
    exception_suffix = "”"
    a = _Assembly()

    def condition():
        a.facet("conditions", condition_prefix, distractor, condition_suffix)

    def exception():
        duration = other_distractor if class_name == "condition_exception_duration" else distractor
        a.facet("exceptions", exception_prefix, duration, exception_suffix)

    # Layout is shared across splits.  The lexical-index alternation adds a
    # second training layout without claiming unseen challenge grammar.
    front_qualifiers = not ambiguous and lexical_index == 1
    if front_qualifiers and has_condition:
        a.append("If ")
        condition()
        a.append(", ")
    if front_qualifiers and has_exception:
        a.append("unless ")
        exception()
        a.append(", ")
    if class_name == "actor_duration_name":
        a.facet("actor", actor + " named “", distractor, "”")
    else:
        a.facet("actor", actor)
    a.append(" ")
    cue = a.append(_CUES[modality])
    a.append(" ")
    a.facet("action", action)
    a.append(" ")
    if class_name == "object_duration_title":
        a.facet("object", obj + " titled “", distractor, "”")
    else:
        a.facet("object", obj)
    if temporal_present:
        a.append(" ")
        a.facet("temporal", "", norm_duration)
    if not front_qualifiers and has_condition:
        a.append(" if ")
        condition()
    if not front_qualifiers and has_exception:
        a.append(" unless ")
        exception()
    a.append(".")
    source = a.source()
    rule = {"modality": modality}
    for field in FIELDS:
        value = a.facets[field]["text"] if a.facets[field] is not None else ""
        rule[field] = [value] if field in QUALIFIERS and value else [] if field in QUALIFIERS else value
    for index, occurrence in enumerate(a.durations):
        occurrence["occurrence_index"] = index
    return {
        "schema": ROW_SCHEMA, "id": identifier, "split": split,
        "group_id": group, "pair_id": pair, "class_name": class_name,
        "pair_variant": "temporal_present" if temporal_present else "temporal_absent",
        "modality": modality, "norm_temporal_present": temporal_present,
        "provenance": PROVENANCE,
        "reference_scope": "authored_flat_copied_roles_not_clock_semantics",
        "prior_exposure": "new_source_strings_shared_authored_grammar_not_independent_holdout",
        "legacy_label_status": "unsupported_ambiguous_temporal_atom" if ambiguous else "expected_supported_unique_atoms",
        "fit_eligible": not ambiguous and split == "train",
        "legacy_labels_supported_expected": not ambiguous,
        "source_sha256": _sha(source), "source_characters": len(source),
        "source_utf8_bytes": len(source.encode("utf-8")),
        "facet_spans": a.facets, "modality_cue_span": cue,
        "duration_occurrences": a.durations,
        "refusal_candidate" if ambiguous else "model_example": {
            "id": identifier, "source_text": source,
            "canonical_ir": {"rules": [rule]}, "latent": [0.0] * LATENT_DIMENSION},
    }


def _build():
    populations, groups, pairs = {}, [], []
    for split in SPLITS:
        rows = []
        for class_name in CLASSES:
            for lexical_index in range(len(_LEXICONS[split])):
                group_rows = []
                group_pairs = []
                for modality in MODALITIES:
                    members = [_row(split, class_name, lexical_index, modality, present)
                               for present in (False, True)]
                    rows.extend(members)
                    group_rows.extend(row["id"] for row in members)
                    pair_id = members[0]["pair_id"]
                    group_pairs.append(pair_id)
                    pairs.append({"pair_id": pair_id, "group_id": members[0]["group_id"],
                                  "split": split, "class_name": class_name, "modality": modality,
                                  "absent_id": members[0]["id"], "present_id": members[1]["id"],
                                  "relation": "only_authored_normative_temporal_presence_changes"})
                groups.append({"group_id": members[0]["group_id"], "split": split,
                               "class_name": class_name, "row_ids": group_rows,
                               "pair_ids": group_pairs,
                               "group_scope": "all_modal_counterfactuals_and_both_presence_states"})
        populations[split] = rows
    populations["ambiguous_diagnostics"] = [
        _row("ambiguous_diagnostics", class_name, 0, modality, True, ambiguous=True)
        for class_name in ("condition_duration", "object_duration_title")
        for modality in MODALITIES
    ]
    return {
        "schema": SCHEMA, "provenance": PROVENANCE, "counts": dict(EXPECTED_COUNTS),
        "populations": populations, "groups": groups, "pairs": pairs,
        "modality_cues": dict(_CUES), "class_order": list(CLASSES),
        "split_contract": {
            "sampling_unit": "case_group_with_six_rows_and_three_pairs",
            "group_counts": {"train": 12, "tuning": 6, "challenge": 6},
            "pair_counts": {"train": 36, "tuning": 18, "challenge": 18},
            "case_group_disjoint": True, "source_strings_disjoint": True,
            "canonical_reference_objects_disjoint": True,
            "shared_templates": True, "structural_novelty_claimed": False,
            "challenge_reference_visibility": "visible_to_builder_author_generated_engineering_only",
            "statutory_section_holdout_created": False,
            "related_statutory_provisions_split": False,
        },
        "latent_contract": {"dimension": LATENT_DIMENSION, "latent_enabled": False,
                            "representation": "zero_placeholder_not_encoder_output",
                            "encoder_identity": None, "latent_decoder_evaluated": False},
        "scope_limits": {
            "one_rule": True, "max_atoms_per_qualifier": 1,
            "clock_origin_defined": False, "calendar_unit_semantics_defined": False,
            "source_roles": "author_declared_fictional",
            "canonical_targets": "copied_flat_O_P_F_roles_only",
            "ambiguous_diagnostics": "never_fit_or_resolve_by_first_occurrence",
            "mask_semantics": "fit_eligible_is_engineering_membership_not_legal_admission",
        },
        "authority": dict(_FALSE),
    }


def build_corpus():
    """Return fresh fixed v1 data; perform no file, model, or compiler action."""
    return _build()


def validate_corpus(corpus):
    """Replay the closed fixed v1 contract, including exact splits and spans.

    Validation does not establish source-semantic truth.  Canonical JSON
    comparison distinguishes booleans from numbers and rejects extra keys,
    moved rows, altered authority claims and partial diagnostic panels.
    """
    if type(corpus) is not dict:
        raise TemporalContrastCorpusError("closed corpus object required")
    try:
        raw = _raw(corpus)
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise TemporalContrastCorpusError("corpus must be finite UTF-8 JSON") from error
    if len(raw) > MAX_CORPUS_BYTES or raw != _raw(_build()):
        raise TemporalContrastCorpusError("corpus differs from closed generated v1 contract")
    return {"schema": "authored-temporal-role-contrast-validation/v1", "passed": True,
            "corpus_sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "counts": dict(EXPECTED_COUNTS), "semantic_gold": False,
            "legacy_label_execution_performed": False, "model_execution_performed": False}


def export_model_examples(corpus, *, split):
    """Export only train/tuning examples for the disabled-latent 384D profile.

    Challenge and ambiguous references require a separate explicit reference
    export.  Corpus-level flags and occurrence maps never enter model inputs.
    """
    validate_corpus(corpus)
    if type(split) is not str or split not in ("train", "tuning"):
        raise TemporalContrastCorpusError("model example export permits train or tuning only")
    return [json.loads(_raw(row["model_example"])) for row in corpus["populations"][split]]


def export_source_panel(corpus, *, split):
    """Export unlabeled source inputs for a declared evaluation population."""
    validate_corpus(corpus)
    if type(split) is not str or split not in EXPECTED_COUNTS:
        raise TemporalContrastCorpusError("unknown source panel split")
    key = "refusal_candidate" if split == "ambiguous_diagnostics" else "model_example"
    return [{"id": row["id"], "source_text": row[key]["source_text"],
             "latent": list(row[key]["latent"])}
            for row in corpus["populations"][split]]


def export_reference_panel(corpus, *, split):
    """Explicit authored reference access, separate from source-only inference.

    The caller must freeze generation/selection before opening challenge
    references if it wants a generated challenge evaluation.  This API cannot
    attest that ordering and grants no independent statutory holdout claim.
    """
    validate_corpus(corpus)
    if type(split) is not str or split not in EXPECTED_COUNTS:
        raise TemporalContrastCorpusError("unknown reference panel split")
    return {"schema": "authored-temporal-role-contrast-reference-panel/v1", "split": split,
            "provenance": PROVENANCE, "reference_access_explicit": True,
            "rows": json.loads(_raw(corpus["populations"][split])),
            "semantic_gold": False, "legal_fidelity_qualified": False,
            "reference_free_generation_verified": False,
            "fit_export_permitted": split in ("train", "tuning")}
