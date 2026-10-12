"""Matched, author-declared temporal curricula; no model or file operations.

The four cells reuse the exact cached 96-row rehearsal population.  Each adds
72 fictional rows in the same slots.  The actor factor moves a long neutral
phrase into a quoted name; the scope factor changes quoted clause ownership
and clause/deadline placement.  Each factor changes only its 12 assigned rows.
Character and UTF-8 lengths are matched slot by slot, including both factors.

Targets come from declared source segments, never a parser's interpretation.
Geometry validation establishes copy custody, not semantic correctness.  The
new development/evaluation groups share authored grammar and are visible to
the builder's author.  Evaluation inputs omit references; opening the separate
reference packet is explicit and cannot attest independent or blind gold.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import itertools
import json

SCHEMA = "matched-temporal-curriculum/v1"
PROVENANCE = "fictional_authored_matched_engineering_not_statutory_gold"
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
QUALIFIERS = FIELDS[3:]
CLASSES = ("plain_deadline", "condition_duration", "exception_duration",
           "actor_duration_name", "object_duration_title", "condition_exception_duration")
MODALITIES = ("O", "P", "F")
CELL_IDS = ("actor0-scope0", "actor0-scope1", "actor1-scope0", "actor1-scope1")
AUTHORED_SPLITS = ("train", "authored_dev", "authored_eval")
META_FIELDS = ("id", "class_name", "group_id", "pair_id", "pair_variant")
LATENT_DIMENSION = 384
PRIOR_EXPORT_FILE_SHA256 = "1992f1c3a3b67d3a3b6d1b01122183e24b537357fc45e928ff5bd747d60825bd"
PRIOR_EXPORT_CANONICAL_SHA256 = "873ce22823139824957043318ab9a19ee342bb51769a3c0ceffa924ae35c6937"
REHEARSAL_SHA256 = "4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995"
EXPOSED_DIAGNOSTICS_SHA256 = "edd5970fe9787bfca51de7a2fe67d8447cbc50d7a8462dfae92008402922b1eb"
REHEARSAL_METADATA_SHA256 = "ad674072ee5026a0ae5ea0df270265785e00cf20fa4ca58c309d73ebb0d6fa72"
EXPOSED_METADATA_SHA256 = "979f3d023aed8a4189ff76def8042a6b9e8f0a6187a0abbd57f2eefd14a6d62a"
MAX_CURRICULUM_BYTES = 32 * 1024 * 1024
REFERENCE_ACCESS = "explicit_author_visible_engineering_references"
_CUES = {"O": "shall", "P": "may", "F": "shall not"}
_LEXICONS = {
    "train": (("Indigoport", "inspect", "register"),
              ("Junipermarsh", "archive", "filing packet")),
    "authored_dev": (("Kestrelford", "retain", "notice"),
                     ("Lindenpoint", "certify", "record dossier")),
    "authored_eval": (("Mallowhaven", "submit", "ledger"),
                      ("Nettlebridge", "deliver", "review packet")),
}
_BASE = {"train": 2100, "authored_dev": 4100, "authored_eval": 6100}
_ROTATION = {"train": 0, "authored_dev": 1, "authored_eval": 2}
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


class MatchedCurriculumError(ValueError):
    """Input provenance, source custody or matched membership differs."""


def _require(condition, message):
    if not condition:
        raise MatchedCurriculumError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clone(value):
    return json.loads(_raw(value))


def _levels(actor, scope):
    _require(type(actor) is int and actor in (0, 1)
             and type(scope) is int and scope in (0, 1), "factor levels must be integer0 or1")


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
    group = "matched-temporal-" + split + "-" + class_name + "-" + str(lexical_index)
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
        "schema": "matched-temporal-authored-row/v1", "id": identifier,
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
        "prior_exposure": "new_source_author_visible_shared_grammar_not_independent_gold",
    }


def build_authored_population(*, split="train", actor_curriculum=0, scope_curriculum=0):
    """Build 72 declared rows; evaluation uses both variants across two groups."""
    _require(type(split) is str and split in AUTHORED_SPLITS, "unknown authored split")
    _levels(actor_curriculum, scope_curriculum)
    _require(split == "train" or actor_curriculum == scope_curriculum == 0,
             "development/evaluation variant mixture is fixed")
    rows = []
    for class_name in CLASSES:
        for lexical_index in range(2):
            actor = actor_curriculum if split == "train" else lexical_index
            scope = scope_curriculum if split == "train" else lexical_index
            for modality, present in itertools.product(MODALITIES, (False, True)):
                rows.append(_new_row(split, class_name, lexical_index, modality, present, actor, scope))
    return rows


def _metadata(rows):
    return [{name: row[name] for name in META_FIELDS} for row in rows]


def _source_only(rows):
    return [{name: _clone(row[name]) for name in ("id", "source_text", "latent")} for row in rows]


def _cache_provenance():
    return {"schema": "authenticated-prior-temporal-export/v1",
            "raw_file_sha256_provenance_only": PRIOR_EXPORT_FILE_SHA256,
            "canonical_export_sha256": PRIOR_EXPORT_CANONICAL_SHA256,
            "rehearsal96_sha256": REHEARSAL_SHA256,
            "rehearsal_metadata_sha256": REHEARSAL_METADATA_SHA256,
            "exposed_diagnostic_populations_sha256": EXPOSED_DIAGNOSTICS_SHA256,
            "exposed_diagnostic_metadata_sha256": EXPOSED_METADATA_SHA256,
            "raw_file_read_or_verified_by_module": False}


def _manifest(examples, metadata):
    return {"rows": len(examples), "examples_sha256": _digest(examples),
            "metadata_sha256": _digest(metadata),
            "slot_ids_sha256": _digest([row["id"] for row in examples])}


def build_curriculum(prior_export):
    """Authenticate cached JSON values and return four matched populations.

    Caller verifies the original raw file SHA separately.  Returned evaluation
    inputs contain no reference or geometry.  Keep geometry_review_packet in a
    separate reference artifact outside numerical-child fit/selection inputs.
    """
    try:
        _require(type(prior_export) is dict and _digest(prior_export) == PRIOR_EXPORT_CANONICAL_SHA256,
                 "exact cached prior export canonical identity required")
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise MatchedCurriculumError("exact finite cached prior export required") from error
    rehearsal = prior_export["populations"]["contrast_train"][:96]
    _require(_digest(rehearsal) == REHEARSAL_SHA256, "exact cached rehearsal96 required")
    legacy_meta = prior_export["metadata"]["contrast_train"][:96]
    populations, metadata, geometries, manifests = {}, {}, {}, {}
    for actor, scope in itertools.product((0, 1), repeat=2):
        cell = "actor" + str(actor) + "-scope" + str(scope)
        rows = build_authored_population(actor_curriculum=actor, scope_curriculum=scope)
        populations[cell] = _clone(rehearsal) + [_clone(row["model_example"]) for row in rows]
        metadata[cell] = _clone(legacy_meta) + _metadata(rows)
        geometries[cell] = rows
        manifests[cell] = _manifest(populations[cell], metadata[cell])
    diagnostics = {name: _clone(prior_export["populations"][name])
                   for name in ("old_tune", "fresh_tune", "fresh_challenge", "law")}
    diag_meta = {name: _clone(prior_export["metadata"][name])
                 for name in ("old_tune", "fresh_tune", "fresh_challenge")}
    panels = {split: build_authored_population(split=split) for split in AUTHORED_SPLITS[1:]}
    diagnostics["authored_dev"] = [_clone(row["model_example"]) for row in panels["authored_dev"]]
    diagnostics["authored_eval"] = _source_only([row["model_example"] for row in panels["authored_eval"]])
    diag_meta.update({split: _metadata(rows) for split, rows in panels.items()})
    value = {
        "schema": SCHEMA, "provenance": PROVENANCE,
        "training_populations": populations, "training_metadata": metadata,
        "diagnostic_populations": diagnostics, "diagnostic_metadata": diag_meta,
        "geometry_review_packet": {"schema": "matched-temporal-author-declaration-packet/v1",
            "training": geometries, "authored_dev": panels["authored_dev"],
            "authored_eval": panels["authored_eval"],
            "provenance": PROVENANCE, "semantic_gold": False,
            "evaluation_references_visible_to_builder_author": True},
        "manifests": {"training": manifests,
            "diagnostic": {name: _manifest(rows, diag_meta.get(name, []))
                           for name, rows in diagnostics.items()}},
        "cache_provenance": _cache_provenance(),
        "slot_contract": {"rows_per_cell": 168, "common_rehearsal_rows": 96,
            "new_authored_rows": 72, "rows_per_fresh_class": 12,
            "class_order": list(CLASSES), "modality_order": list(MODALITIES),
            "presence_order": [False, True], "stable_ID_and_order_across_cells": True,
            "actor_replacement_slots": list(range(132, 144)),
            "scope_replacement_slots": list(range(156, 168)),
            "slot_character_and_UTF8_lengths_matched": True,
            "rehearsal_repetition_or_sampler_modified": False},
        "split_contract": {"authored_dev_rows": 72, "authored_eval_rows": 72,
            "new_source_ID_pair_provision_lexical_groups_disjoint": True,
            "prior_panels_exposed_diagnostics_only": True,
            "evaluation_references_in_diagnostic_populations": False,
            "geometry_packet_permitted_in_numerical_inputs": False,
            "authored_evaluation_membership_frozen": True,
            "reference_access_or_selection_order_attested": False,
            "shared_authored_templates": True, "statutory_provision_holdout": False},
        "latent_contract": {"dimension": LATENT_DIMENSION, "latent_enabled": False,
                            "fresh_vectors": "zero_placeholder_not_encoder_output",
                            "legacy_vectors": "exact_cached_disabled_transport"},
        "authority": dict(_AUTHORITY),
    }
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
        _require(row["schema"] == "matched-temporal-authored-row/v1" and row["split"] == split,
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
        expected_group = "matched-temporal-" + split + "-" + row["class_name"] + "-" + str(lexical_index)
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
        _require(type(source) is str and source and source not in sources and len(source) <= 4096,
                 "unique bounded source required")
        _require(type(example["latent"]) is list and len(example["latent"]) == 384
                 and all(type(v) is float and v == 0.0 for v in example["latent"]), "fresh zero float384 placeholder required")
        _require(row["source_sha256"] == _sha(source) and type(row["source_characters"]) is int
                 and row["source_characters"] == len(source) and type(row["source_utf8_bytes"]) is int
                 and row["source_utf8_bytes"] == len(source.encode("utf-8")), "source custody differs")
        _require(row["fit_eligible"] is (split == "train")
                 and row["reference_scope"] == "author_declared_flat_copied_roles_not_clock_semantics"
                 and row["prior_exposure"] == "new_source_author_visible_shared_grammar_not_independent_gold",
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
    return {"passed": True, "rows": 72, "groups": 12, "pairs": 36,
            "geometry_only_not_semantic_verification": True}


def validate_curriculum(value):
    """Validate finite matched data and separation; perform no semantic parse."""
    top = {"schema", "provenance", "training_populations", "training_metadata", "diagnostic_populations",
           "diagnostic_metadata", "geometry_review_packet", "manifests", "cache_provenance", "slot_contract",
           "split_contract", "latent_contract", "authority"}
    _require(type(value) is dict and set(value) == top, "closed curriculum required")
    try:
        raw = _raw(value)
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise MatchedCurriculumError("finite curriculum JSON required") from error
    _require(len(raw) <= MAX_CURRICULUM_BYTES and value["schema"] == SCHEMA and value["provenance"] == PROVENANCE,
             "bounded matched curriculum identity differs")
    _require(_raw(value["cache_provenance"]) == _raw(_cache_provenance()) and _raw(value["authority"]) == _raw(_AUTHORITY),
             "cache provenance or authority differs")
    train, meta, diag, diag_meta = (value[n] for n in ("training_populations", "training_metadata", "diagnostic_populations", "diagnostic_metadata"))
    _require(type(train) is dict and type(meta) is dict and set(train) == set(meta) == set(CELL_IDS), "complete four-cell population required")
    _require(type(diag) is dict and type(diag_meta) is dict
             and set(diag) == {"old_tune", "fresh_tune", "fresh_challenge", "authored_dev", "authored_eval", "law"}
             and set(diag_meta) == set(diag) - {"law"}, "complete diagnostic populations required")
    manifests = value["manifests"]
    _require(type(manifests) is dict and set(manifests) == {"training", "diagnostic"}
             and type(manifests["training"]) is dict and set(manifests["training"]) == set(CELL_IDS)
             and type(manifests["diagnostic"]) is dict and set(manifests["diagnostic"]) == set(diag),
             "closed complete manifest maps required")
    packet = value["geometry_review_packet"]
    _require(type(packet) is dict and set(packet) == {"schema", "training", "authored_dev", "authored_eval", "provenance", "semantic_gold",
             "evaluation_references_visible_to_builder_author"}
             and packet["schema"] == "matched-temporal-author-declaration-packet/v1"
             and packet["provenance"] == PROVENANCE and packet["semantic_gold"] is False
             and packet["evaluation_references_visible_to_builder_author"] is True
             and set(packet["training"]) == set(CELL_IDS), "separate declared geometry packet differs")
    baseline = train[CELL_IDS[0]][:96]
    _require(_digest(baseline) == REHEARSAL_SHA256, "cached rehearsal96 changed")
    _require(_digest(meta[CELL_IDS[0]][:96]) == REHEARSAL_METADATA_SHA256, "cached rehearsal metadata changed")
    for cell in CELL_IDS:
        _require(type(train[cell]) is list and type(meta[cell]) is list and len(train[cell]) == 168 and len(meta[cell]) == 168
                 and train[cell][:96] == baseline and meta[cell][:96] == meta[CELL_IDS[0]][:96], "matched168/common96 differs")
        rows = packet["training"][cell]
        validate_authored_population(rows, split="train")
        _require(train[cell][96:] == [r["model_example"] for r in rows]
                 and meta[cell][96:] == _metadata(rows), "model data/geometry/metadata join differs")
        for example, metadata in zip(train[cell], meta[cell], strict=True):
            _require(set(metadata) == set(META_FIELDS) and example["id"] == metadata["id"], "closed model metadata differs")
        _require(len({r["id"] for r in train[cell]}) == len({r["source_text"] for r in train[cell]}) == 168,
                 "within-cell source/ID duplicates")
    reference = train[CELL_IDS[0]]
    for cell in CELL_IDS:
        actor, scope = int(cell[5]), int(cell[-1])
        expected = set(range(132, 144)) if actor else set()
        if scope:
            expected |= set(range(156, 168))
        actual = {i for i, (a, b) in enumerate(zip(reference, train[cell], strict=True)) if a != b}
        _require(actual == expected, "factors change unassigned or missing slots")
        _require([r["id"] for r in train[cell]] == [r["id"] for r in reference], "stable slot IDs differ")
        _require(all(len(a["source_text"]) == len(b["source_text"])
                     and len(a["source_text"].encode("utf-8")) == len(b["source_text"].encode("utf-8"))
                     for a, b in zip(reference, train[cell], strict=True)), "factor source length confound")
        _require(value["manifests"]["training"][cell] == _manifest(train[cell], meta[cell]), "training manifest differs")
    exposed = {name: diag[name] for name in ("old_tune", "fresh_tune", "fresh_challenge", "law")}
    _require(_digest(exposed) == EXPOSED_DIAGNOSTICS_SHA256, "exposed diagnostic bytes changed")
    _require(_digest({name: diag_meta[name] for name in ("old_tune", "fresh_tune", "fresh_challenge")}) == EXPOSED_METADATA_SHA256,
             "exposed diagnostic metadata changed")
    for split in AUTHORED_SPLITS[1:]:
        rows = packet[split]
        validate_authored_population(rows, split=split)
        expected = [r["model_example"] for r in rows]
        _require(diag[split] == (_source_only(expected) if split == "authored_eval" else expected)
                 and diag_meta[split] == _metadata(rows), "authored panel/source-only gate differs")
    for name, examples in diag.items():
        _require(value["manifests"]["diagnostic"][name] == _manifest(examples, diag_meta.get(name, [])), "diagnostic manifest differs")
    # Across cells, identical training groups are intentionally repeated.  They
    # are never allowed to cross into development/evaluation or exposed panels.
    new_sets = {}
    for split in AUTHORED_SPLITS:
        rows = [r for cell in CELL_IDS for r in packet["training"][cell]] if split == "train" else packet[split]
        new_sets[split] = {key: {r[key] for r in rows} for key in ("id", "group_id", "pair_id", "provision_group_id", "lexical_group_id")}
        new_sets[split]["source"] = {r["model_example"]["source_text"] for r in rows}
    for left, right in itertools.combinations(AUTHORED_SPLITS, 2):
        _require(all(not new_sets[left][key] & new_sets[right][key] for key in new_sets[left]), "new split group/source leakage")
    exposed_sources = {r["source_text"] for rows in exposed.values() for r in rows} | {r["source_text"] for r in baseline}
    _require(all(not info["source"] & exposed_sources for info in new_sets.values()), "exposed source occurrence reused")
    slot = value["slot_contract"]
    _require(type(slot) is dict and set(slot) == {"rows_per_cell", "common_rehearsal_rows", "new_authored_rows",
             "rows_per_fresh_class", "class_order", "modality_order", "presence_order", "stable_ID_and_order_across_cells",
             "actor_replacement_slots", "scope_replacement_slots", "slot_character_and_UTF8_lengths_matched",
             "rehearsal_repetition_or_sampler_modified"}, "closed slot contract required")
    _require(all(type(slot[key]) is int for key in ("rows_per_cell", "common_rehearsal_rows", "new_authored_rows", "rows_per_fresh_class"))
             and all(type(v) is int for key in ("actor_replacement_slots", "scope_replacement_slots") for v in slot[key]),
             "integer slot counts and coordinates required")
    _require(slot["rows_per_cell"] == 168 and type(slot["rows_per_cell"]) is int
             and slot["common_rehearsal_rows"] == 96 and slot["new_authored_rows"] == 72
             and slot["rows_per_fresh_class"] == 12 and slot["class_order"] == list(CLASSES)
             and slot["modality_order"] == list(MODALITIES) and _raw(slot["presence_order"]) == _raw([False, True])
             and slot["actor_replacement_slots"] == list(range(132, 144))
             and slot["scope_replacement_slots"] == list(range(156, 168))
             and slot["stable_ID_and_order_across_cells"] is True
             and slot["slot_character_and_UTF8_lengths_matched"] is True
             and slot["rehearsal_repetition_or_sampler_modified"] is False, "slot contract differs")
    contract = value["split_contract"]
    _require(type(contract) is dict and set(contract) == {"authored_dev_rows", "authored_eval_rows",
             "new_source_ID_pair_provision_lexical_groups_disjoint", "prior_panels_exposed_diagnostics_only",
             "evaluation_references_in_diagnostic_populations", "geometry_packet_permitted_in_numerical_inputs",
             "authored_evaluation_membership_frozen", "reference_access_or_selection_order_attested",
             "shared_authored_templates", "statutory_provision_holdout"}, "closed split contract required")
    _require(type(contract["authored_dev_rows"]) is int and type(contract["authored_eval_rows"]) is int,
             "integer authored split counts required")
    _require(contract["authored_dev_rows"] == contract["authored_eval_rows"] == 72
             and contract["new_source_ID_pair_provision_lexical_groups_disjoint"] is True
             and contract["prior_panels_exposed_diagnostics_only"] is True
             and contract["evaluation_references_in_diagnostic_populations"] is False
             and contract["geometry_packet_permitted_in_numerical_inputs"] is False
             and contract["authored_evaluation_membership_frozen"] is True
             and contract["reference_access_or_selection_order_attested"] is False
             and contract["shared_authored_templates"] is True
             and contract["statutory_provision_holdout"] is False, "authored evaluation disclosure differs")
    _require(_raw(value["latent_contract"]) == _raw({"dimension": 384, "latent_enabled": False,
             "fresh_vectors": "zero_placeholder_not_encoder_output", "legacy_vectors": "exact_cached_disabled_transport"}),
             "source-only latent contract differs")
    return {"schema": "matched-temporal-curriculum-validation/v1", "passed": True,
            "curriculum_sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "training_rows_per_cell": 168, "new_dev_rows": 72, "new_eval_rows": 72,
            "semantic_gold": False, "model_execution_performed": False,
            "parser_generated_targets": False, "reference_access_order_attested": False}


def export_training_examples(value, *, cell):
    validate_curriculum(value)
    _require(type(cell) is str and cell in CELL_IDS, "unknown matched training cell")
    return _clone(value["training_populations"][cell])


def export_source_panel(value, *, split):
    validate_curriculum(value)
    _require(type(split) is str and split in value["diagnostic_populations"], "unknown diagnostic split")
    return _source_only(value["diagnostic_populations"][split])


def export_reference_panel(value, *, split, reference_access):
    validate_curriculum(value)
    _require(type(split) is str and split in AUTHORED_SPLITS[1:]
             and type(reference_access) is str and reference_access == REFERENCE_ACCESS,
             "explicit author-visible reference access required")
    return {"schema": "matched-temporal-explicit-reference-panel/v1", "split": split,
            "rows": _clone(value["geometry_review_packet"][split]), "semantic_gold": False,
            "reference_access_explicit": True, "reference_access_order_attested": False,
            "references_visible_to_builder_author": True, "fit_export_permitted": False}


def export_annotation_packet(value, *, split, mode="source_only"):
    """Give independent annotators source-only blanks or declared copy spans."""
    validate_curriculum(value)
    _require(type(split) is str and split in AUTHORED_SPLITS[1:]
             and type(mode) is str and mode in ("source_only", "author_declared_review"), "unknown annotation packet mode")
    records = []
    for row in value["geometry_review_packet"][split]:
        record = {key: row[key] for key in ("id", "group_id", "pair_id", "provision_group_id", "lexical_group_id", "source_sha256")}
        record.update(source_text=row["model_example"]["source_text"], annotation_status="not_reviewed",
                      annotation=None, reviewer_id=None, adjudication=None)
        if mode == "author_declared_review":
            record["author_declaration"] = {key: _clone(row[key]) for key in
                ("facet_spans", "modality_cue_span", "duration_occurrences")}
            record["author_canonical_ir"] = _clone(row["model_example"]["canonical_ir"])
        records.append(record)
    return {"schema": "matched-temporal-annotation-packet/v1", "split": split, "mode": mode,
            "rows": records, "semantic_gold": False, "independently_reviewed": False,
            "author_declarations_visible": mode == "author_declared_review",
            "review_response_can_establish_legal_gold_without_separate_provenance": False}
