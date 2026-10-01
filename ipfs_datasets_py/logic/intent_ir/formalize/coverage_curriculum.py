"""Additive, weakly supervised Intent source-form coverage curriculum.

Independent authored lexical groups exercise missing *forms*, never copy a
rejected evaluation sentence. Source and semantic aliases are quarantined at
partition boundaries. The frozen rich grammar supplies transparent weak labels;
none of these labels is a learned prediction or verified natural-language fact.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from . import rich_grammar as grammar
from .rich_decoder import sha, wire

SCHEMA = "intent-source-form-coverage-curriculum/v1"
ACTIONS = ("save", "view", "use", "reuse", "run", "create", "fetch")
OBJECT_SHAPES = ("short", "long_five", "long_eight", "extension", "numeric_range",
                 "quoted_command", "quoted_path", "case_sensitive")
SURFACE_FORMS = ("bare", "bare_article", "please_article", "negative_article",
                 "never_article", "required_article", "permitted_article",
                 "recommended_article", "explicit_actor_article")
_BANKS = {
    "train": ("archive", "ledger", "journal", "bundle", "snapshot", "digest", "segment", "receipt"),
    "validation": ("catalog", "parcel", "envelope", "register", "roster", "dossier", "notebook", "memo"),
    "test": ("inventory", "packet", "folio", "capsule", "transcript", "voucher", "recording", "brochure"),
}
_ADJECTIVES = ("local", "stable", "durable", "compact", "recent", "portable", "trusted", "cached")


def _source_identity(text):
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy import tokenize
    return tuple(tokenize(grammar.model_input(text)))


def _semantic_identities(ast):
    output = {grammar.ast_to_sequence(ast)}
    if ast["kind"] == "if":
        output.add(grammar.ast_to_sequence(ast["body"]))
    elif ast["kind"] in {"and", "or", "then"}:
        output.update(grammar.ast_to_sequence(ast[key]) for key in ("left", "right"))
    return output


def _source_identities(row):
    output = {_source_identity(row["instruction"])}
    if row["ast"]["kind"] != "atom":
        from .compositional_decoder import _source_parts
        output.update(_source_identity(part["text"])
                      for part in _source_parts(row["instruction"], row["ast"]["kind"])
                      if not part["role"].startswith("symbolic_"))
    return output


def _validated_rows(corpus):
    if type(corpus) is not dict or type(corpus.get("samples")) is not list:
        raise ValueError("explicit rich corpus samples required")
    identities, labels, families = set(), {}, {}
    for row in corpus["samples"]:
        if (type(row) is not dict or type(row.get("id")) is not str
                or row.get("split") not in {"train", "validation", "test"}
                or type(row.get("instruction")) is not str
                or type(row.get("provenance")) is not dict):
            raise ValueError("source-bound samples with declared partitions required")
        if row["id"] in identities:
            raise ValueError("duplicate corpus sample identity")
        identities.add(row["id"])
        if grammar.parse_instruction(row["instruction"]) != grammar.validate_ast(row["ast"]):
            raise ValueError("source and weak grammar AST differ")
        key, target = _source_identity(row["instruction"]), grammar.ast_to_sequence(row["ast"])
        if key in labels and labels[key] != target:
            raise ValueError("conflicting tokenized source labels")
        labels[key] = target
        family = row["provenance"].get("source_family_id")
        if family is not None:
            if type(family) is not str or not family:
                raise ValueError("stable source family identity required")
            if family in families and families[family] != row["split"]:
                raise ValueError("source family crosses partitions")
            families[family] = row["split"]
    return corpus["samples"]


def _object(split, group):
    bank = _BANKS[split]
    noun, adjective = bank[group % len(bank)], _ADJECTIVES[(group // len(bank)) % len(_ADJECTIVES)]
    # Numeric suffix distinguishes larger independently authored source groups;
    # the bounded default needs no suffix. Group IDs never come from heldout text.
    serial = "" if group < 64 else str(group // 64)
    stem = adjective + " " + noun + serial
    shape = OBJECT_SHAPES[group % len(OBJECT_SHAPES)]
    objects = {
        "short": stem,
        "long_five": stem + " under durable disk storage",
        "long_eight": stem + " under durable disk storage with verified checksum metadata",
        "extension": ".cfg " + stem + " beside compressed disk artifacts",
        "numeric_range": stem + " for 3-7x aggregate throughput diagnostics",
        "quoted_command": "`orbit " + noun + serial + "` for " + adjective + " disk diagnostics",
        "quoted_path": "`assets/" + noun + serial + ".cfg` beside " + adjective + " disk artifacts",
        "case_sensitive": "API " + noun.title() + serial + " metrics under " + adjective + " storage",
    }
    return shape, objects[shape]


def _render(action, object_, form):
    ast = {"kind": "atom", "actor": "unspecified", "action": action,
           "object": object_, "modality": "intended"}
    templates = {
        "bare": "{action} {object}.",
        "bare_article": "{action} the {object}.",
        "please_article": "Please {action} the {object}.",
        "negative_article": "Do not {action} the {object}.",
        "never_article": "Never {action} the {object}.",
        "required_article": "Must {action} the {object}.",
        "permitted_article": "May {action} the {object}.",
        "recommended_article": "Should {action} the {object}.",
        "explicit_actor_article": "The operator intends to {action} the {object}.",
    }
    ast["modality"] = {"negative_article": "prohibited", "never_article": "prohibited",
                       "required_article": "required", "permitted_article": "permitted",
                       "recommended_article": "recommended"}.get(form, "intended")
    if form == "explicit_actor_article":
        ast["actor"] = "operator"
    text = templates[form].format(action=action, object=object_)
    text = text[0].upper() + text[1:]
    if grammar.parse_instruction(text) != ast:
        raise ValueError("authored source form differs from declared weak AST")
    return text, ast


def build_coverage_curriculum(parent_corpus, *, groups_per_split=None, forbidden_sources=()):
    """Preserve parent rows and append independent, partitioned source forms.

    ``forbidden_sources`` is an exclusion list, never a source of new examples.
    Semantic aliases in heldout atoms *or compound leaves* fence off training.
    Existing parent partition defects remain recorded and are quarantined by
    :func:`prepare_coverage_training_data`, without silently rewriting history.
    """
    parent = _validated_rows(parent_corpus)
    groups = {"train": 15, "validation": 8, "test": 8} if groups_per_split is None else dict(groups_per_split)
    if (set(groups) != {"train", "validation", "test"}
            or any(type(value) is not int or not 1 <= value <= 256 for value in groups.values())):
        raise ValueError("bounded lexical group counts required for all three partitions")
    if type(forbidden_sources) not in (tuple, list) or any(type(x) is not str for x in forbidden_sources):
        raise ValueError("explicit source exclusion strings required")
    excluded_inputs = {_source_identity(text) for text in forbidden_sources}
    excluded_semantics = set()
    for text in forbidden_sources:
        try:
            excluded_semantics.update(_semantic_identities(grammar.parse_instruction(text)))
        except ValueError:
            pass
    source_splits, semantic_splits = defaultdict(set), defaultdict(set)
    existing_sources = set()
    for row in parent:
        existing_sources.add(_source_identity(row["instruction"]))
        for key in _source_identities(row):
            source_splits[key].add(row["split"])
        for key in _semantic_identities(row["ast"]):
            semantic_splits[key].add(row["split"])
    added, omitted = [], []
    for split in ("test", "validation", "train"):
        for group in range(groups[split]):
            shape, object_ = _object(split, group)
            family = f"intent-source-form:{split}:{group}"
            for action in ACTIONS:
                for form in SURFACE_FORMS:
                    text, ast = _render(action, object_, form)
                    source, target = _source_identity(text), grammar.ast_to_sequence(ast)
                    reasons = []
                    if source in excluded_inputs or target in excluded_semantics:
                        reasons.append("explicit_source_or_semantic_exclusion")
                    if source_splits[source] - {split} or semantic_splits[target] - {split}:
                        reasons.append("cross_partition_source_or_semantic_alias")
                    if source in existing_sources:
                        reasons.append("duplicate_existing_or_added_source")
                    identity = f"{family}:{action}:{form}"
                    if reasons:
                        omitted.append({"id": identity, "split": split, "reasons": reasons})
                        continue
                    added.append({"id": identity, "split": split, "instruction": text, "ast": ast,
                        "provenance": {"kind": "authored_source_form_coverage", "source_family_id": family,
                            "lexical_bank_partition": split, "object_shape": shape, "surface_form": form,
                            "source_sha256": sha(text.encode()), "label_rule": "authored_ast_checked_by_frozen_rich_grammar/v1",
                            "semantic_gold": False, "source_semantics_verified": False,
                            "model_predictions_used": False, "evaluation_sentence_derived": False}})
                    source_splits[source].add(split)
                    semantic_splits[target].add(split)
                    existing_sources.add(source)
    result = deepcopy(parent_corpus)
    result["samples"].extend(added)
    result["split_counts"] = dict(Counter(row["split"] for row in result["samples"]))
    result["kind_counts"] = dict(Counter(row["ast"]["kind"] for row in result["samples"]))
    result["source_form_coverage"] = {"schema": SCHEMA, "parent_corpus_sha256": sha(wire(parent_corpus)),
        "groups_per_split": groups, "original_rows": len(parent), "added_rows": len(added),
        "added_split_counts": dict(Counter(row["split"] for row in added)), "omitted": omitted,
        "source_exclusion_sha256": sha(wire(list(forbidden_sources))),
        "original_rows_preserved": True, "existing_heldout_rows_changed": False,
        "heldout_inputs_used_to_author_examples": False, "predictions_used": False,
        "supervision": "independent authored templates with deterministic weak grammar labels",
        "producer_sha256": sha(Path(__file__).read_bytes())}
    return result


def prepare_coverage_training_data(corpus, *, family_target_builder=None):
    """Return paired training/tuning views and explicit projection supervision.

    All test content is excluded from fitting and tuning. It is inspected only
    for collision quarantine. Family targets stay beside source/IR pairs: an
    existing two-direction decoder cannot silently claim a new logic direction.
    """
    from .rich_training import build_pairs
    rows = _validated_rows(corpus)
    if family_target_builder is not None and not callable(family_target_builder):
        raise ValueError("callable explicit family target builder required")
    banned_sources, banned_semantics = {}, {}
    for split in ("train", "validation"):
        heldout = [r for r in rows if r["split"] == "test" or (split == "train" and r["split"] == "validation")]
        banned_sources[split] = set().union(*(_source_identities(row) for row in heldout)) if heldout else set()
        banned_semantics[split] = set().union(*(_semantic_identities(row["ast"]) for row in heldout)) if heldout else set()
    selected, omitted = {"train": [], "validation": []}, []
    for row in rows:
        split = row["split"]
        if split == "test":
            continue
        if (_source_identities(row) & banned_sources[split]
                or _semantic_identities(row["ast"]) & banned_semantics[split]):
            omitted.append({"id": row["id"], "split": split, "reason": "heldout_source_or_semantic_alias"})
        else:
            selected[split].append(row)
    pairs = {split: build_pairs(subset) for split, subset in selected.items()}
    family_targets = []
    if family_target_builder is not None:
        for split, subset in selected.items():
            for row in subset:
                bundle = family_target_builder("intent_ir", document=deepcopy(row["ast"]), source_text=row["instruction"])
                if (type(bundle) is not dict or bundle.get("source_sha256") != sha(row["instruction"].encode())
                        or type(bundle.get("projections")) is not list or type(bundle.get("family_inventory")) is not list):
                    raise ValueError("source-bound family inventory and actual projection rows required")
                family_targets.append({"sample_id": row["id"], "split": split, "bundle": bundle})
    return {"schema": "intent-source-form-training-data/v1", "corpus_sha256": sha(wire(corpus)),
        "pairs": pairs, "selected_row_ids": {split: [r["id"] for r in subset] for split, subset in selected.items()},
        "quarantined": omitted, "family_targets": family_targets,
        "family_targets_status": "prepared" if family_target_builder is not None else "explicit_builder_required",
        "family_targets_are_neural_directions": False, "test_used_for_fit_or_tuning": False,
        "supervision_is_semantic_gold": False, "training_executed": False}


def freeze_coverage_holdouts(corpus, *, per_shape_per_split=1):
    """Choose new heldout IDs by a fixed hash before any model inference."""
    rows = _validated_rows(corpus)
    if type(per_shape_per_split) is not int or not 1 <= per_shape_per_split <= 8:
        raise ValueError("bounded per-shape evaluation size required")
    groups = defaultdict(list)
    for row in rows:
        if row["split"] != "train" and row["provenance"].get("kind") == "authored_source_form_coverage":
            groups[(row["split"], row["provenance"]["object_shape"], row["ast"]["action"])].append(row)
    selected = []
    for key, candidates in sorted(groups.items()):
        candidates.sort(key=lambda row: sha((SCHEMA + ":evaluation:" + row["id"]).encode()))
        selected.extend(deepcopy(candidates[:per_shape_per_split]))
    return {"schema": "intent-source-form-frozen-evaluation/v1", "corpus_sha256": sha(wire(corpus)),
        "selection_rule": "SHA256(schema:evaluation:ID), per partition/object shape/action",
        "per_shape_per_split": per_shape_per_split, "rows": selected,
        "model_predictions_consulted": False, "prior_development_sets_reused": False,
        "supervision_is_semantic_gold": False, "producer_sha256": sha(Path(__file__).read_bytes())}


__all__ = ["SCHEMA", "ACTIONS", "OBJECT_SHAPES", "SURFACE_FORMS", "build_coverage_curriculum",
           "prepare_coverage_training_data", "freeze_coverage_holdouts"]
