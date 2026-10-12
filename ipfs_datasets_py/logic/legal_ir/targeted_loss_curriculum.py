"""A fixed mixed authored population for targeted decoder-loss comparisons.

All four loss-policy cells consume the same168 examples.  The first96 are
unchanged rehearsal occurrences; the remaining72 retain the previous matched
slots/IDs.  Actor and combined-scope classes each mix six control and six hard
layouts.  Newly authored dev/eval occurrences use disjoint fictional groups,
lexicons and quantities, but share the author's grammar and are not legal gold.
The model evaluation export has exactly id/source_text/latent.  The separate
geometry/reference packet must stay outside every numerical child until all
four new cell outputs are frozen; this module cannot attest that access order.
No model, tokenizer, file, resource, compiler or network operation is performed.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import itertools
import json
import re

from . import matched_temporal_curriculum as matched

SCHEMA = "targeted-loss-curriculum/v1"
PROVENANCE = "fictional_authored_mixed_layout_targeted_loss_not_statutory_gold"
FIELDS = matched.FIELDS
QUALIFIERS = matched.QUALIFIERS
CLASSES = matched.CLASSES
MODALITIES = matched.MODALITIES
AUTHORED_SPLITS = ("train", "authored_dev", "authored_eval")
CELL_IDS = ("mixed",)
META_FIELDS = matched.META_FIELDS
LATENT_DIMENSION = 384
PRIOR_EXPORT_FILE_SHA256 = matched.PRIOR_EXPORT_FILE_SHA256
PRIOR_EXPORT_CANONICAL_SHA256 = matched.PRIOR_EXPORT_CANONICAL_SHA256
REHEARSAL_SHA256 = matched.REHEARSAL_SHA256
REHEARSAL_METADATA_SHA256 = matched.REHEARSAL_METADATA_SHA256
EXPOSED_DIAGNOSTICS_SHA256 = matched.EXPOSED_DIAGNOSTICS_SHA256
EXPOSED_METADATA_SHA256 = matched.EXPOSED_METADATA_SHA256
OLD_AUTHORED_EVAL_SHA256 = "6a8ebd09b4c84de6c7d2e463519338e23836cebeb73205f3c40aaef207d0956b"
OLD_AUTHORED_EVAL_METADATA_SHA256 = "36adc69c69196f94060644f9b15661d900abb271bf9ce2a6fa2775647100a9c2"
MAX_CURRICULUM_BYTES = 16 * 1024 * 1024
MAX_SOURCE_CHARACTERS = 239
MAX_SOURCE_TOKENS = 128
REFERENCE_ACCESS = "explicit_author_visible_targeted_loss_engineering_references"
_CUES = {"O": "shall", "P": "may", "F": "shall not"}
_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_LEXICONS = {
    "train": (("Indigoport", "inspect", "register"),
              ("Junipermarsh", "archive", "filing packet")),
    "authored_dev": (("Orchidford", "approve", "report"),
                     ("Pollenpoint", "verify", "record packet")),
    "authored_eval": (("Quarryhaven", "retain", "ticket"),
                      ("Reedbridge", "record", "audit dossier")),
}
_BASE = {"train": 2100, "authored_dev": 7100, "authored_eval": 9100}
_ROTATION = {"train": 0, "authored_dev": 2, "authored_eval": 0}
_ACTOR_EXTENSION = " for Licensed Records and Public Archive Custody"
_AUTHORITY = {name: False for name in (
    "semantic_gold", "independently_reviewed", "legal_fidelity_qualified",
    "independent_semantic_holdout", "structural_novelty_claimed", "family_qualified",
    "Lake_executed", "training_executed", "model_execution_performed",
    "encoder_execution_performed", "default_promoted")}
_ROW_FIELDS = {"schema", "id", "slot_index", "split", "class_name", "group_id",
               "pair_id", "pair_variant", "provision_group_id", "lexical_group_id",
               "modality", "norm_temporal_present", "actor_variant", "scope_variant",
               "source_sha256", "source_characters", "source_utf8_bytes", "facet_spans",
               "modality_cue_span", "duration_occurrences", "model_example",
               "fit_eligible", "reference_scope", "prior_exposure"}
_PANEL_ROWS = {"old_tune": 96, "fresh_tune": 36, "fresh_challenge": 36,
               "old_authored_eval": 72, "authored_dev": 72, "authored_eval": 72, "law": 8}
_METADATA_PANELS = set(_PANEL_ROWS) - {"authored_eval", "law"}


class TargetedCurriculumError(ValueError):
    """Input provenance, source custody or fixed membership differs."""


def _require(condition, message):
    if not condition:
        raise TargetedCurriculumError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clone(value):
    return json.loads(_raw(value))


def source_token_count(source):
    """Structural lexemes only; no learned tokenizer is imported or executed."""
    _require(type(source) is str, "text source required")
    return len(_TOKEN.findall(source))


def _group_prefix(split):
    return "matched-temporal" if split == "train" else "targeted-loss"


def _exposure(split):
    return ("previously_exposed_training_occurrences_fixed_mixed_layout"
            if split == "train" else
            "new_source_author_visible_shared_grammar_not_independent_gold")


def _levels(actor, scope):
    _require(type(actor) is int and actor in (0, 1)
             and type(scope) is int and scope in (0, 1), "layout levels must be integer0 or1")


class _Assembly:
    """Record declared segments as appended, without searching source text."""

    def __init__(self):
        self.parts, self.characters, self.bytes = [], 0, 0
        self.facets = {name: None for name in FIELDS}
        self.durations = []

    def append(self, text):
        start, byte_start = self.characters, self.bytes
        self.parts.append(text)
        self.characters += len(text)
        self.bytes += len(text.encode("utf-8"))
        return {"char_start": start, "char_end": self.characters,
                "utf8_byte_start": byte_start, "utf8_byte_end": self.bytes,
                "text": text, "text_sha256": _sha(text)}

    def facet(self, role, prefix, quantity=None, suffix=""):
        start, byte_start = self.characters, self.bytes
        self.append(prefix)
        if quantity is not None:
            span = self.append("within " + str(quantity) + " days")
            self.durations.append({"role": role, "normative": role == "temporal",
                                   "quantity": quantity, "span": span,
                                   "occurrence_index": len(self.durations)})
        self.append(suffix)
        text = prefix + ("within " + str(quantity) + " days" if quantity is not None else "") + suffix
        self.facets[role] = {"char_start": start, "char_end": self.characters,
                             "utf8_byte_start": byte_start, "utf8_byte_end": self.bytes,
                             "text": text, "text_sha256": _sha(text)}


def _new_row(split, class_name, lexical_index, modality, present, actor, scope):
    index = CLASSES.index(class_name)
    stem, action, object_name = _LEXICONS[split][lexical_index]
    name = stem + str(index)
    base = _BASE[split] + index * 100 + lexical_index * 20
    rotation = (index + lexical_index + _ROTATION[split]) % 3
    normative = base + rotation + 1
    distractor = base + (rotation + 1) % 3 + 1
    other = base + (rotation + 2) % 3 + 1
    group = _group_prefix(split) + "-" + split + "-" + class_name + "-" + str(lexical_index)
    pair = group + "-" + modality.lower()
    identifier = pair + ("-present" if present else "-absent")
    slot = index * 12 + lexical_index * 6 + MODALITIES.index(modality) * 2 + int(present)
    actor_variant = actor if class_name == "actor_duration_name" else 0
    scope_variant = scope if class_name == "condition_exception_duration" else 0
    has_condition = class_name in ("condition_duration", "condition_exception_duration")
    has_exception = class_name in ("exception_duration", "condition_exception_duration")
    a = _Assembly()

    def condition():
        if class_name == "condition_exception_duration":
            # Quote location changes; the same words and quote bytes are retained.
            if scope_variant:
                a.facet("conditions", "the " + name.lower() + " application was received “",
                        distractor, "” of publication")
            else:
                a.facet("conditions", "the “" + name.lower() + " application” was received ",
                        distractor, " of publication")
        else:
            a.facet("conditions", "the " + name.lower() + " application was received ",
                    distractor, " of publication")

    def exception():
        a.facet("exceptions", "the " + name.lower() + " waiver notice states “",
                other if class_name == "condition_exception_duration" else distractor, "”")

    front = lexical_index == 1 and (has_condition or has_exception)
    reverse_front = front and scope_variant == 1
    if front:
        if reverse_front:
            a.append("Unless ")
            exception()
            a.append(", if ")
            condition()
            a.append(", ")
        else:
            if has_condition:
                a.append("If ")
                condition()
                a.append(", ")
            if has_exception:
                a.append("unless ")
                exception()
                a.append(", ")
    actor_name = "the " + name + " Office"
    if class_name == "actor_duration_name":
        if actor_variant:
            a.facet("actor", actor_name + " named “", distractor, _ACTOR_EXTENSION + "”")
        else:
            a.facet("actor", actor_name + _ACTOR_EXTENSION + " named “", distractor, "”")
    else:
        a.facet("actor", actor_name)
    a.append(" ")
    cue = a.append(_CUES[modality])
    a.append(" ")
    a.facet("action", action)
    a.append(" ")
    object_text = "the " + name.lower() + " " + object_name
    if class_name == "object_duration_title":
        a.facet("object", object_text + " titled “", distractor, "”")
    else:
        a.facet("object", object_text)
    distant_deadline = scope_variant == 1 and not front
    if present and not distant_deadline:
        a.append(" ")
        a.facet("temporal", "", normative)
    if not front:
        if has_condition:
            a.append(" if ")
            condition()
        if has_exception:
            a.append(" unless ")
            exception()
    if present and distant_deadline:
        a.append(" ")
        a.facet("temporal", "", normative)
    a.append(".")
    source = "".join(a.parts)
    # Both source and reference use these authored facet declarations.  No
    # tokenizer, parser, decoder or inferred modality creates the reference.
    rule = {"modality": modality}
    for field in FIELDS:
        value = a.facets[field]["text"] if a.facets[field] is not None else ""
        rule[field] = [value] if field in QUALIFIERS and value else [] if field in QUALIFIERS else value
    return {
        "schema": "targeted-loss-authored-row/v1", "id": identifier,
        "slot_index": slot + (96 if split == "train" else 0), "split": split,
        "class_name": class_name, "group_id": group, "pair_id": pair,
        "pair_variant": "temporal_present" if present else "temporal_absent",
        "provision_group_id": "fictional-provision-" + group,
        "lexical_group_id": "fictional-lexicon-" + split + "-" + stem,
        "modality": modality, "norm_temporal_present": present,
        "actor_variant": actor_variant, "scope_variant": scope_variant,
        "source_sha256": _sha(source), "source_characters": len(source),
        "source_utf8_bytes": len(source.encode("utf-8")),
        "facet_spans": a.facets, "modality_cue_span": cue,
        "duration_occurrences": a.durations,
        "model_example": {"id": identifier, "source_text": source,
                          "canonical_ir": {"rules": [rule]}, "latent": [0.0] * LATENT_DIMENSION},
        "fit_eligible": split == "train",
        "reference_scope": "author_declared_flat_copied_roles_not_clock_semantics",
        "prior_exposure": _exposure(split),
    }



def build_authored_population(*, split="train"):
    """Build the fixed72-row mixture, with six control/hard rows per target class."""
    _require(type(split) is str and split in AUTHORED_SPLITS, "unknown authored split")
    rows = []
    for class_name in CLASSES:
        for lexical_index in range(2):
            for modality, present in itertools.product(MODALITIES, (False, True)):
                rows.append(_new_row(split, class_name, lexical_index, modality, present,
                                     lexical_index, lexical_index))
    return rows


def _metadata(rows):
    return [{name: row[name] for name in META_FIELDS} for row in rows]


def _source_only(rows):
    return [{name: _clone(row[name]) for name in ("id", "source_text", "latent")} for row in rows]


def _manifest(examples, metadata):
    return {"rows": len(examples), "examples_sha256": _digest(examples),
            "metadata_sha256": _digest(metadata),
            "slot_ids_sha256": _digest([row["id"] for row in examples])}


def _old_authored_eval():
    rows = matched.build_authored_population(split="authored_eval")
    _require(_digest([r["model_example"] for r in rows]) == OLD_AUTHORED_EVAL_SHA256
             and _digest(_metadata(rows)) == OLD_AUTHORED_EVAL_METADATA_SHA256,
             "exact previously exposed authored evaluation required")
    matched.validate_authored_population(rows, split="authored_eval")
    return rows


def _cache_provenance():
    return {"schema": "authenticated-prior-temporal-and-matched-export/v1",
            "raw_file_sha256_provenance_only": PRIOR_EXPORT_FILE_SHA256,
            "canonical_export_sha256": PRIOR_EXPORT_CANONICAL_SHA256,
            "rehearsal96_sha256": REHEARSAL_SHA256,
            "rehearsal_metadata_sha256": REHEARSAL_METADATA_SHA256,
            "exposed_diagnostic_populations_sha256": EXPOSED_DIAGNOSTICS_SHA256,
            "exposed_diagnostic_metadata_sha256": EXPOSED_METADATA_SHA256,
            "exposed_old_authored_eval72_sha256": OLD_AUTHORED_EVAL_SHA256,
            "exposed_old_authored_eval_metadata_sha256": OLD_AUTHORED_EVAL_METADATA_SHA256,
            "raw_file_read_or_verified_by_module": False}


def _slot_contract():
    return {"rows_per_population": 168, "common_rehearsal_rows": 96,
            "new_authored_rows": 72, "rows_per_fresh_class": 12,
            "class_order": list(CLASSES), "modality_order": list(MODALITIES),
            "presence_order": [False, True], "training_population_key": "mixed",
            "one_common_population_for_four_loss_policy_cells": True,
            "prior_matched_slot_ID_and_order_preserved": True,
            "actor_mixed_slots": list(range(132, 144)),
            "scope_mixed_slots": list(range(156, 168)),
            "control_hard_rows_per_target_class": [6, 6],
            "per_layout_modality_counts": {name: 2 for name in MODALITIES},
            "per_layout_temporal_presence_counts": {"absent": 3, "present": 3},
            "prior_matched_slot_character_UTF8_token_counts_preserved": True,
            "rehearsal_repetition_or_sampler_modified": False}


def _split_contract():
    return {"authored_dev_rows": 72, "authored_eval_rows": 72,
            "old_authored_eval_rows_exposed": 72,
            "new_dev_eval_source_ID_pair_provision_lexical_groups_disjoint": True,
            "new_dev_eval_disjoint_from_all_previous_matched_authored_panels": True,
            "training_occurrences_previously_exposed": True,
            "prior_panels_exposed_diagnostics_only": True,
            "evaluation_references_in_diagnostic_populations": False,
            "evaluation_metadata_in_diagnostic_metadata": False,
            "geometry_packet_permitted_in_numerical_inputs": False,
            "new_reference_packet_forbidden_until_all_four_cell_outputs_frozen": True,
            "reference_access_or_selection_order_attested": False,
            "shared_authored_templates": True, "statutory_provision_holdout": False}


def _latent_contract():
    return {"dimension": LATENT_DIMENSION, "latent_enabled": False,
            "fresh_vectors": "zero_placeholder_not_encoder_output",
            "legacy_vectors": "exact_cached_disabled_transport"}


def _panel_contract():
    return {"rows": dict(_PANEL_ROWS),
            "exposed_regression_panels": ["old_tune", "fresh_tune", "fresh_challenge", "old_authored_eval"],
            "development_can_inform_loss_choices": True,
            "authored_eval_child_keys": ["id", "source_text", "latent"],
            "law_has_independently_reviewed_targets": False,
            "law_scoring_permitted": False,
            "maximum_new_source_characters": MAX_SOURCE_CHARACTERS,
            "maximum_all_panel_source_structural_tokens": MAX_SOURCE_TOKENS}


def build_curriculum(prior_export):
    """Authenticate finite prior cached data; return one fixed training population.

    The caller checks the original raw-file hash.  The returned geometry packet
    contains author-visible evaluation references; separate it before numerical
    launch and permit access only after all four cell outputs are frozen.
    """
    try:
        _require(type(prior_export) is dict and _digest(prior_export) == PRIOR_EXPORT_CANONICAL_SHA256,
                 "exact cached prior export canonical identity required")
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise TargetedCurriculumError("exact finite cached prior export required") from error
    rehearsal = prior_export["populations"]["contrast_train"][:96]
    _require(_digest(rehearsal) == REHEARSAL_SHA256, "exact cached rehearsal96 required")
    legacy_meta = prior_export["metadata"]["contrast_train"][:96]
    train_rows = build_authored_population(split="train")
    train = _clone(rehearsal) + [_clone(r["model_example"]) for r in train_rows]
    train_meta = _clone(legacy_meta) + _metadata(train_rows)
    diagnostics = {name: _clone(prior_export["populations"][name])
                   for name in ("old_tune", "fresh_tune", "fresh_challenge", "law")}
    diag_meta = {name: _clone(prior_export["metadata"][name])
                 for name in ("old_tune", "fresh_tune", "fresh_challenge")}
    old_eval = _old_authored_eval()
    panels = {split: build_authored_population(split=split) for split in AUTHORED_SPLITS[1:]}
    diagnostics["old_authored_eval"] = [_clone(r["model_example"]) for r in old_eval]
    diag_meta["old_authored_eval"] = _metadata(old_eval)
    diagnostics["authored_dev"] = [_clone(r["model_example"]) for r in panels["authored_dev"]]
    diag_meta["authored_dev"] = _metadata(panels["authored_dev"])
    diagnostics["authored_eval"] = _source_only([r["model_example"] for r in panels["authored_eval"]])
    value = {"schema": SCHEMA, "provenance": PROVENANCE,
        "training_populations": {"mixed": train}, "training_metadata": {"mixed": train_meta},
        "diagnostic_populations": diagnostics, "diagnostic_metadata": diag_meta,
        "geometry_review_packet": {"schema": "targeted-loss-author-declaration-packet/v1",
            "training": {"mixed": train_rows}, "authored_dev": panels["authored_dev"],
            "authored_eval": panels["authored_eval"], "old_authored_eval": old_eval,
            "provenance": PROVENANCE, "semantic_gold": False,
            "evaluation_references_visible_to_builder_author": True,
            "reference_access_order_attested": False},
        "manifests": {"training": {"mixed": _manifest(train, train_meta)},
            "diagnostic": {name: _manifest(rows, diag_meta.get(name, []))
                           for name, rows in diagnostics.items()}},
        "cache_provenance": _cache_provenance(), "slot_contract": _slot_contract(),
        "split_contract": _split_contract(), "latent_contract": _latent_contract(),
        "panel_contract": _panel_contract(), "authority": dict(_AUTHORITY)}
    validate_curriculum(value)
    return value


def _validate_span(source, span):
    _require(type(span) is dict and set(span) == {"char_start", "char_end", "utf8_byte_start",
             "utf8_byte_end", "text", "text_sha256"}, "closed source span required")
    _require(all(type(span[key]) is int for key in ("char_start", "char_end", "utf8_byte_start", "utf8_byte_end")),
             "integer span coordinates required")
    start, end = span["char_start"], span["char_end"]
    _require(0 <= start < end <= len(source) and source[start:end] == span["text"], "character source span differs")
    _require(span["utf8_byte_start"] == len(source[:start].encode("utf-8"))
             and span["utf8_byte_end"] == len(source[:end].encode("utf-8"))
             and span["text_sha256"] == _sha(span["text"]), "UTF8/hash source span differs")


def validate_authored_population(rows, *, split):
    """Check geometry and balanced pairs without interpreting source semantics."""
    _require(type(split) is str and split in AUTHORED_SPLITS, "unknown authored split")
    _require(type(rows) is list and len(rows) == 72, "complete72 authored population required")
    identifiers, sources, groups, pairs = set(), set(), {}, {}
    tally = Counter()
    for position, row in enumerate(rows):
        _require(type(row) is dict and set(row) == _ROW_FIELDS, "closed authored row required")
        _require(row["schema"] == "targeted-loss-authored-row/v1" and row["split"] == split,
                 "authored row identity differs")
        _require(type(row["slot_index"]) is int and row["slot_index"] == position + (96 if split == "train" else 0),
                 "stable ordered slot differs")
        _require(row["class_name"] == CLASSES[position // 12]
                 and row["modality"] == MODALITIES[position % 6 // 2]
                 and type(row["norm_temporal_present"]) is bool
                 and row["norm_temporal_present"] is bool(position % 2), "class/modal/presence order differs")
        _levels(row["actor_variant"], row["scope_variant"])
        _require(row["actor_variant"] == 0 or row["class_name"] == "actor_duration_name", "actor factor outside assigned class")
        _require(row["scope_variant"] == 0 or row["class_name"] == "condition_exception_duration", "scope factor outside assigned class")
        for key in ("id", "group_id", "pair_id", "provision_group_id", "lexical_group_id"):
            _require(type(row[key]) is str and row[key], "declared group/ID required")
        lexical_index = position % 12 // 6
        expected_group = _group_prefix(split) + "-" + split + "-" + row["class_name"] + "-" + str(lexical_index)
        expected_pair = expected_group + "-" + row["modality"].lower()
        _require(row["group_id"] == expected_group and row["pair_id"] == expected_pair
                 and row["provision_group_id"] == "fictional-provision-" + expected_group
                 and row["lexical_group_id"] == "fictional-lexicon-" + split + "-" + _LEXICONS[split][lexical_index][0]
                 and row["id"] == expected_pair + ("-present" if row["norm_temporal_present"] else "-absent"),
                 "declared frozen group/occurrence membership differs")
        example = row["model_example"]
        _require(type(example) is dict and set(example) == {"id", "source_text", "canonical_ir", "latent"}
                 and example["id"] == row["id"] and row["id"] not in identifiers, "closed unique example required")
        source = example["source_text"]
        _require(type(source) is str and source and source not in sources and len(source) <= MAX_SOURCE_CHARACTERS
                 and source_token_count(source) <= MAX_SOURCE_TOKENS,
                 "unique bounded source required")
        _require(type(example["latent"]) is list and len(example["latent"]) == 384
                 and all(type(v) is float and v == 0.0 for v in example["latent"]), "fresh zero float384 placeholder required")
        _require(row["source_sha256"] == _sha(source) and type(row["source_characters"]) is int
                 and row["source_characters"] == len(source) and type(row["source_utf8_bytes"]) is int
                 and row["source_utf8_bytes"] == len(source.encode("utf-8")), "source custody differs")
        _require(row["fit_eligible"] is (split == "train")
                 and row["reference_scope"] == "author_declared_flat_copied_roles_not_clock_semantics"
                 and row["prior_exposure"] == _exposure(split),
                 "authored exposure/admission declarations differ")
        _require(type(example["canonical_ir"]) is dict and set(example["canonical_ir"]) == {"rules"}
                 and type(example["canonical_ir"]["rules"]) is list and len(example["canonical_ir"]["rules"]) == 1,
                 "one authored rule required")
        rule = example["canonical_ir"]["rules"][0]
        _require(type(rule) is dict and set(rule) == {"modality", *FIELDS}
                 and rule["modality"] == row["modality"] and type(row["facet_spans"]) is dict
                 and set(row["facet_spans"]) == set(FIELDS), "closed rule/facets differ")
        active = []
        for field in FIELDS:
            span = row["facet_spans"][field]
            if span is None:
                _require(field in QUALIFIERS and rule[field] == [], "required facet absent")
                continue
            _validate_span(source, span)
            expected = [span["text"]] if field in QUALIFIERS else span["text"]
            _require(rule[field] == expected and source.count(span["text"]) == 1, "declared unique copied atom differs")
            active.append((span["char_start"], span["char_end"]))
        _require(bool(rule["temporal"]) is row["norm_temporal_present"], "temporal presence differs")
        _require(all(a[1] <= b[0] or b[1] <= a[0] for a, b in itertools.combinations(active, 2)), "declared facet overlap")
        _validate_span(source, row["modality_cue_span"])
        _require(row["modality_cue_span"]["text"] == _CUES[row["modality"]], "modality cue differs")
        occurrences = row["duration_occurrences"]
        _require(type(occurrences) is list, "duration declarations required")
        for index, occurrence in enumerate(occurrences):
            _require(type(occurrence) is dict and set(occurrence) == {"role", "normative", "quantity", "span", "occurrence_index"},
                     "closed duration declaration required")
            role = occurrence["role"]
            _require(role in FIELDS and occurrence["normative"] is (role == "temporal")
                     and type(occurrence["quantity"]) is int and occurrence["quantity"] > 0
                     and type(occurrence["occurrence_index"]) is int and occurrence["occurrence_index"] == index,
                     "duration role/count/type differs")
            _validate_span(source, occurrence["span"])
            outer = row["facet_spans"][role]
            _require(outer is not None and outer["char_start"] <= occurrence["span"]["char_start"]
                     < occurrence["span"]["char_end"] <= outer["char_end"]
                     and occurrence["span"]["text"] == "within " + str(occurrence["quantity"]) + " days",
                     "duration is outside declared owner facet")
        _require(sum(o["normative"] for o in occurrences) == int(row["norm_temporal_present"]), "normative duration count differs")
        _require(len({o["span"]["text"] for o in occurrences}) == len(occurrences), "ambiguous repeated duration cannot fit")
        _require(row["pair_variant"] == ("temporal_present" if row["norm_temporal_present"] else "temporal_absent"), "pair variant differs")
        identifiers.add(row["id"])
        sources.add(source)
        groups.setdefault(row["group_id"], []).append(row)
        pairs.setdefault(row["pair_id"], []).append(row)
        tally[(row["class_name"], row["modality"], row["norm_temporal_present"])] += 1
    _require(len(groups) == 12 and len(pairs) == 36
             and set(tally) == set(itertools.product(CLASSES, MODALITIES, (False, True)))
             and set(tally.values()) == {2}, "balanced authored groups/pairs differ")
    for members in groups.values():
        _require(len(members) == 6 and len({r["provision_group_id"] for r in members}) == 1
                 and len({r["lexical_group_id"] for r in members}) == 1
                 and {(r["modality"], r["norm_temporal_present"]) for r in members} == set(itertools.product(MODALITIES, (False, True))),
                 "whole modal/presence provision group required")
    for members in pairs.values():
        _require(len(members) == 2 and {r["norm_temporal_present"] for r in members} == {False, True}
                 and len({r["group_id"] for r in members}) == 1, "complete co-owned pair required")
        left, right = [_clone(r["model_example"]["canonical_ir"]["rules"][0]) for r in members]
        left.pop("temporal")
        right.pop("temporal")
        _require(left == right, "pair changes a non-temporal declared facet")
    expected_rows = build_authored_population(split=split)
    _require(_raw(rows) == _raw(expected_rows), "fixed authored declarations differ")
    for field, class_name in (("actor_variant", "actor_duration_name"),
                              ("scope_variant", "condition_exception_duration")):
        members = [r for r in rows if r["class_name"] == class_name]
        _require(Counter(r[field] for r in members) == {0: 6, 1: 6}, "fixed mixed layout quota differs")
        for layout in (0, 1):
            selected = [r for r in members if r[field] == layout]
            _require(Counter(r["modality"] for r in selected) == {name: 2 for name in MODALITIES}
                     and Counter(r["norm_temporal_present"] for r in selected) == {False: 3, True: 3},
                     "mixed layout modality/presence quota differs")
    return {"passed": True, "rows": 72, "groups": 12, "pairs": 36,
            "geometry_only_not_semantic_verification": True}



def _identities(rows):
    out = {key: {r[key] for r in rows} for key in
           ("id", "group_id", "pair_id", "provision_group_id", "lexical_group_id")}
    out["source"] = {r["model_example"]["source_text"] for r in rows}
    return out


def validate_curriculum(value):
    """Check finite custody, fixed examples and deferred-reference declarations.

    Fixed declaration equality and span geometry are engineering contracts.
    They establish neither source-law semantics nor an independently blind set.
    """
    top = {"schema", "provenance", "training_populations", "training_metadata",
           "diagnostic_populations", "diagnostic_metadata", "geometry_review_packet",
           "manifests", "cache_provenance", "slot_contract", "split_contract",
           "latent_contract", "panel_contract", "authority"}
    _require(type(value) is dict and set(value) == top, "closed curriculum required")
    try:
        raw = _raw(value)
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise TargetedCurriculumError("finite curriculum JSON required") from error
    _require(len(raw) <= MAX_CURRICULUM_BYTES and value["schema"] == SCHEMA
             and value["provenance"] == PROVENANCE, "bounded targeted curriculum identity differs")
    expected_contracts = {"cache_provenance": _cache_provenance(), "slot_contract": _slot_contract(),
        "split_contract": _split_contract(), "latent_contract": _latent_contract(),
        "panel_contract": _panel_contract(), "authority": _AUTHORITY}
    for name, expected in expected_contracts.items():
        _require(_raw(value[name]) == _raw(expected), "closed " + name + " differs")
    train, meta, diag, diag_meta = (value[n] for n in
        ("training_populations", "training_metadata", "diagnostic_populations", "diagnostic_metadata"))
    _require(type(train) is dict and type(meta) is dict and set(train) == set(meta) == {"mixed"},
             "one common mixed training population required")
    _require(type(diag) is dict and type(diag_meta) is dict
             and set(diag) == set(_PANEL_ROWS) and set(diag_meta) == _METADATA_PANELS,
             "closed seven diagnostic panels/five metadata panels required")
    _require(type(train["mixed"]) is list and type(meta["mixed"]) is list
             and len(train["mixed"]) == len(meta["mixed"]) == 168,
             "fixed168 training examples/metadata required")
    _require(_digest(train["mixed"][:96]) == REHEARSAL_SHA256
             and _digest(meta["mixed"][:96]) == REHEARSAL_METADATA_SHA256,
             "cached rehearsal96 or metadata changed")
    packet = value["geometry_review_packet"]
    _require(type(packet) is dict and set(packet) == {"schema", "training", "authored_dev", "authored_eval",
             "old_authored_eval", "provenance", "semantic_gold", "evaluation_references_visible_to_builder_author",
             "reference_access_order_attested"}
             and packet["schema"] == "targeted-loss-author-declaration-packet/v1"
             and packet["provenance"] == PROVENANCE and packet["semantic_gold"] is False
             and packet["evaluation_references_visible_to_builder_author"] is True
             and packet["reference_access_order_attested"] is False
             and type(packet["training"]) is dict and set(packet["training"]) == {"mixed"},
             "separate authored reference/geometry packet differs")
    training_rows = packet["training"]["mixed"]
    validate_authored_population(training_rows, split="train")
    _require(train["mixed"][96:] == [r["model_example"] for r in training_rows]
             and meta["mixed"][96:] == _metadata(training_rows),
             "training example/geometry/metadata join differs")
    _require(len({r["id"] for r in train["mixed"]}) == len({r["source_text"] for r in train["mixed"]}) == 168,
             "training ID/source duplicates")
    for example, metadata in zip(train["mixed"], meta["mixed"], strict=True):
        _require(type(metadata) is dict and set(metadata) == set(META_FIELDS)
                 and example["id"] == metadata["id"], "closed training metadata join differs")
    previous = {(a, s): matched.build_authored_population(actor_curriculum=a, scope_curriculum=s)
                for a, s in itertools.product((0, 1), repeat=2)}
    for position, row in enumerate(training_rows):
        layout = position % 12 // 6
        _require(row["model_example"] == previous[(layout, layout)][position]["model_example"],
                 "mixed slot is not the prior declared control/hard occurrence")
        control = previous[(0, 0)][position]
        left, right = control["model_example"]["source_text"], row["model_example"]["source_text"]
        _require(row["id"] == control["id"] and row["slot_index"] == control["slot_index"]
                 and len(left) == len(right) and len(left.encode("utf-8")) == len(right.encode("utf-8"))
                 and source_token_count(left) == source_token_count(right),
                 "prior matched slot ID/order/source geometry differs")
    exposed = {name: diag[name] for name in ("old_tune", "fresh_tune", "fresh_challenge", "law")}
    _require(_digest(exposed) == EXPOSED_DIAGNOSTICS_SHA256,
             "previously exposed diagnostic examples changed")
    _require(_digest({name: diag_meta[name] for name in ("old_tune", "fresh_tune", "fresh_challenge")})
             == EXPOSED_METADATA_SHA256, "previously exposed diagnostic metadata changed")
    old_eval = _old_authored_eval()
    _require(_raw(packet["old_authored_eval"]) == _raw(old_eval)
             and diag["old_authored_eval"] == [r["model_example"] for r in old_eval]
             and diag_meta["old_authored_eval"] == _metadata(old_eval),
             "previously exposed authored evaluation references changed")
    for split in AUTHORED_SPLITS[1:]:
        rows = packet[split]
        validate_authored_population(rows, split=split)
        examples = [r["model_example"] for r in rows]
        _require(diag[split] == (_source_only(examples) if split == "authored_eval" else examples),
                 "new authored panel/source-only export gate differs")
        if split == "authored_dev":
            _require(diag_meta[split] == _metadata(rows), "authored development metadata join differs")
    for name, count in _PANEL_ROWS.items():
        _require(type(diag[name]) is list and len(diag[name]) == count, "fixed diagnostic row count differs")
        _require(len({r["id"] for r in diag[name]}) == len({r["source_text"] for r in diag[name]}) == count,
                 "diagnostic ID/source duplicates")
        if name in _METADATA_PANELS:
            _require(type(diag_meta[name]) is list and len(diag_meta[name]) == count, "diagnostic metadata count differs")
            for example, metadata in zip(diag[name], diag_meta[name], strict=True):
                _require(type(metadata) is dict and set(metadata) == set(META_FIELDS)
                         and example["id"] == metadata["id"], "closed diagnostic metadata join differs")
        for example in diag[name]:
            _require(type(example["source_text"]) is str and example["source_text"]
                     and source_token_count(example["source_text"]) <= MAX_SOURCE_TOKENS,
                     "all-panel128 structural-token bound differs")
    _require(all(source_token_count(r["source_text"]) <= MAX_SOURCE_TOKENS for r in train["mixed"]),
             "training128 structural-token bound differs")
    _require(all(set(r) == {"id", "source_text", "latent"} for r in diag["authored_eval"]),
             "evaluation references/metadata leaked into child examples")
    new_sets = {"train": _identities(training_rows)}
    new_sets.update({split: _identities(packet[split]) for split in AUTHORED_SPLITS[1:]})
    for left, right in itertools.combinations(AUTHORED_SPLITS, 2):
        _require(all(not new_sets[left][key] & new_sets[right][key] for key in new_sets[left]),
                 "new split source/ID/pair/provision/lexical leakage")
    old_rows = [r for rows in previous.values() for r in rows]
    old_rows += matched.build_authored_population(split="authored_dev") + old_eval
    old_sets = _identities(old_rows)
    prior_sources = {r["source_text"] for rows in exposed.values() for r in rows}
    prior_sources |= {r["source_text"] for r in train["mixed"][:96]}
    for split in AUTHORED_SPLITS[1:]:
        _require(all(not new_sets[split][key] & old_sets[key] for key in old_sets)
                 and not new_sets[split]["source"] & prior_sources,
                 "new dev/eval overlaps old authored or exposed source occurrences")
    manifests = value["manifests"]
    expected_manifests = {"training": {"mixed": _manifest(train["mixed"], meta["mixed"])},
        "diagnostic": {name: _manifest(rows, diag_meta.get(name, [])) for name, rows in diag.items()}}
    _require(type(manifests) is dict and _raw(manifests) == _raw(expected_manifests),
             "closed complete manifest maps differ")
    return {"schema": "targeted-loss-curriculum-validation/v1", "passed": True,
            "curriculum_sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "training_population_count": 1, "training_rows_per_population": 168,
            "new_dev_rows": 72, "new_eval_rows": 72, "exposed_old_eval_rows": 72,
            "all_panel_max_structural_tokens": max(source_token_count(r["source_text"])
                for rows in [train["mixed"], *diag.values()] for r in rows),
            "semantic_gold": False, "model_execution_performed": False,
            "parser_generated_targets": False, "reference_access_order_attested": False}


def export_training_examples(value, *, cell="mixed"):
    validate_curriculum(value)
    _require(type(cell) is str and cell == "mixed", "only the common mixed training population is available")
    return _clone(value["training_populations"]["mixed"])


def export_source_panel(value, *, split):
    validate_curriculum(value)
    _require(type(split) is str and split in _PANEL_ROWS, "unknown diagnostic split")
    return _source_only(value["diagnostic_populations"][split])


def export_reference_panel(value, *, split, reference_access):
    validate_curriculum(value)
    _require(type(split) is str and split in (*AUTHORED_SPLITS[1:], "old_authored_eval")
             and type(reference_access) is str and reference_access == REFERENCE_ACCESS,
             "explicit author-visible reference access required")
    return {"schema": "targeted-loss-explicit-reference-panel/v1", "split": split,
            "rows": _clone(value["geometry_review_packet"][split]), "semantic_gold": False,
            "prior_exposed_regression_diagnostic": split == "old_authored_eval",
            "reference_access_explicit": True, "reference_access_order_attested": False,
            "new_reference_packet_forbidden_until_all_four_cell_outputs_frozen": True,
            "references_visible_to_builder_author": True, "fit_export_permitted": False}


def export_annotation_packet(value, *, split, mode="source_only"):
    """Provide source-only annotation blanks or the author's copy declarations."""
    validate_curriculum(value)
    _require(type(split) is str and split in AUTHORED_SPLITS[1:]
             and type(mode) is str and mode in ("source_only", "author_declared_review"),
             "unknown annotation packet mode")
    records = []
    for row in value["geometry_review_packet"][split]:
        record = {key: row[key] for key in ("id", "group_id", "pair_id", "provision_group_id",
                                          "lexical_group_id", "source_sha256")}
        record.update(source_text=row["model_example"]["source_text"], annotation_status="not_reviewed",
                      annotation=None, reviewer_id=None, adjudication=None)
        if mode == "author_declared_review":
            record["author_declaration"] = {key: _clone(row[key]) for key in
                ("facet_spans", "modality_cue_span", "duration_occurrences")}
            record["author_canonical_ir"] = _clone(row["model_example"]["canonical_ir"])
        records.append(record)
    return {"schema": "targeted-loss-annotation-packet/v1", "split": split, "mode": mode,
            "rows": records, "semantic_gold": False, "independently_reviewed": False,
            "author_declarations_visible": mode == "author_declared_review",
            "review_response_can_establish_legal_gold_without_separate_provenance": False}


def registration_contract(value):
    """Return finite expected provenance/counts; do not register or read resources."""
    validation = validate_curriculum(value)
    return {"schema": "targeted-loss-expected-registration/v1", "provenance": PROVENANCE,
            "curriculum_sha256": validation["curriculum_sha256"],
            "training_population": "mixed", "training_rows": 168,
            "training_examples_sha256": value["manifests"]["training"]["mixed"]["examples_sha256"],
            "diagnostic_panel_rows": dict(_PANEL_ROWS), "diagnostic_metadata_panels": sorted(_METADATA_PANELS),
            "authored_eval_child_keys": ["id", "source_text", "latent"],
            "all_panel_max_structural_tokens": validation["all_panel_max_structural_tokens"],
            "latent_dimension": 384, "latent_enabled": False,
            "reference_access_order_attested": False,
            "new_reference_packet_forbidden_until_all_four_cell_outputs_frozen": True,
            "semantic_gold": False, "model_execution_performed": False,
            "resource_API_calls_performed": False}
