"""Sealed, broader normative wordings derived only from original TRAIN rules.

This pure builder consults no parser, encoder, checkpoint or evaluation label.
The caller authenticates input files and enforces the seal before native
preparation. Supplied hashes bind declarations; they do not prove that lifecycle,
independent authorship, source-semantic correctness or Lake admission.
"""
from collections import Counter
from copy import deepcopy
import json
import random

from . import authored_scalar_holdout as base
from . import authored_training_paraphrases as original
from . import authored_modality_holdout_v3 as exclusion

SCHEMA = "normative-wording-training-sources/v1"
SEED = 20261006
TEMPLATES = ("explicit_actor_status_v1", "regulation_norm_operator_v1")
GERUNDS = dict(approve="approving", deliver="delivering", examine="examining",
               preserve="preserving", publish="publishing")
REQUIRED_PRIOR_DATASETS = (
    "original_train_bank", "raw_train", "raw_validation", "raw_test", "raw_canary",
    "paragraph_train", "paragraph_validation", "exposed_r6", "exposed_r8",
    "exposed_v3", "r4_training_paraphrases", "composition64",
)
REQUIRED_PRIOR_COUNTS = dict(original_train_bank=180, raw_train=180,
                            raw_validation=60, raw_test=60, raw_canary=30,
                            paragraph_train=48, paragraph_validation=48,
                            exposed_r6=48, exposed_r8=48, exposed_v3=48,
                            r4_training_paraphrases=48, composition64=64)
FALSE = dict(original.FALSE, source_alignment_reviewed=False,
             source_semantics_reviewed=False, independent_human_review=False,
             downloads_performed=False, evaluation_scored=False,
             encoder_context_increased=False)
digest, text_sha, _require = base.digest, base.text_sha, base._require


def _empty_qualifiers(rule):
    _require(type(rule) is dict and set(rule) == base._RULE_KEYS,
             "complete unchanged seven-field original TRAIN rule required")
    _require(all(type(rule[k]) is list and not rule[k]
                 for k in ("conditions", "exceptions", "temporal")),
             "nonempty or incompatible qualifier cannot be rendered; no dropped qualifier")


def sentence(template, rule):
    """Render a complete compatible TRAIN rule without parsing or rewriting it."""
    _empty_qualifiers(rule)
    actor, action, obj, modality = (rule[k] for k in ("actor", "action", "object", "modality"))
    _require(template in TEMPLATES and actor in base.ACTORS and action in base.ACTIONS
             and obj in base.OBJECTS and modality in base.MODALITIES,
             "closed authored lexical inventory and declared TRAIN template required")
    if template == TEMPLATES[0]:
        if modality == "F":
            return f"Under this regulation, the {actor} is prohibited from {GERUNDS[action]} the {obj}."
        predicate = dict(O="obliged", P="authorized")[modality]
        return f"Under this regulation, the {actor} is {predicate} to {action} the {obj}."
    if modality == "O":
        return f"This regulation places a duty on the {actor} to {action} the {obj}."
    if modality == "P":
        return f"This regulation grants the {actor} permission to {action} the {obj}."
    return f"This regulation bans the {actor} from {GERUNDS[action]} the {obj}."


def _training_bank(rows, codec, validate_rule):
    # Reuse the exact existing 32V codec and complete original180 bank validator.
    # Check qualifiers before its general coverage refusal so future facets are
    # explicitly rejected rather than inadvertently ignored by the renderer.
    base._codec(codec)
    _require(type(rows) is list and len(rows) == 180,
             "complete original180 TRAIN bank required")
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text", "target_ids"},
                 "closed original TRAIN row required; no vectors or evaluation labels")
        ids = row["target_ids"]
        _require(type(ids) is list and 3 <= len(ids) <= 512
                 and all(type(i) is int for i in ids) and ids[0] == 1 and ids[-1] == 2
                 and all(3 <= i < 32 for i in ids[1:-1]),
                 "complete original32V target required")
        target = json.loads("".join(codec["target_vocabulary"][i] for i in ids[1:-1]))
        _require(type(target) is dict and set(target) == {"rules"}
                 and type(target["rules"]) is list and len(target["rules"]) == 1,
                 "single complete original TRAIN rule required")
        _empty_qualifiers(target["rules"][0])
    return original._bank(rows, codec, validate_rule)


def _prior_inventory(inventories, training_bank):
    _require(type(inventories) is dict
             and set(REQUIRED_PRIOR_DATASETS).issubset(inventories),
             "all ten R4 inventories plus R4 wordings and composition64 required")
    forbidden, prior_ids, reports = exclusion._blacklist(inventories)
    _require(all(len(inventories[name]) == count
                 for name, count in REQUIRED_PRIOR_COUNTS.items()),
             "complete saved prior inventory counts differ; no partial exclusion corpus")
    # Normalization alone cannot authenticate the bank's named provenance.
    expected = {row["id"]: row["source_text"] for row in training_bank}
    actual = {row["id"]: row["source_text"] for row in inventories["original_train_bank"]}
    _require(actual == expected and len(inventories["original_train_bank"]) == 180,
             "named original TRAIN source inventory differs from complete bank")
    literals = {text_sha(text) for rows in inventories.values() for row in rows
                for text in (row["source_text"], *row["source_text"].split("\n\n"))}
    return forbidden, literals, prior_ids, reports


def _stratum_rules(rules, ordinal):
    groups = {}
    for key, rule in rules.items():
        group = tuple(rule[k] for k in ("actor", "action", "object"))
        modalities = groups.setdefault(group, {})
        _require(rule["modality"] not in modalities, "duplicate original content-group modality")
        modalities[rule["modality"]] = key
    _require(len(groups) == 30 and all(set(v) == set(base.MODALITIES) for v in groups.values()),
             "thirty complete original O/P/F content groups required")
    rng = random.Random(SEED + ordinal)
    ordered = sorted(groups)
    rng.shuffle(ordered)
    variants = {}
    for group in ordered:
        keys = [groups[group][modality] for modality in base.MODALITIES]
        rng.shuffle(keys)
        variants[group] = keys
    return [variants[group][round_] for round_ in range(3) for group in ordered]


def build(*, training_bank, prior_sources_by_dataset, codec, sealed_recipe_sha256,
          validate_rule, seed=SEED):
    """Build 48 source-only paragraphs and separate complete TRAIN references.

    Inputs use the existing builder's closed row contracts. All twelve named
    exclusion inventories are mandatory; further named source-only cohorts,
    including a separately sealed future development set, are also excluded.
    Any collision refuses the whole generation. No surviving subset is returned.

    ``source_rows`` is suitable for the unchanged pure
    ``training_paraphrase_source_inputs.source_plan`` API: it contains exactly
    216 unique paragraph/clause strings, including twelve paragraph aliases.
    Reference records never enter that source-only plan.
    """
    _require(type(seed) is int and seed == SEED, "fixed nonboolean normative wording seed required")
    _require(type(sealed_recipe_sha256) is str and base._SHA.fullmatch(sealed_recipe_sha256),
             "explicit sealed recipe SHA256 required")
    rules, derivations = _training_bank(training_bank, codec, validate_rule)
    forbidden, prior_literals, prior_ids, inventory = _prior_inventory(prior_sources_by_dataset, training_bank)
    rows, references, clause_references = [], [], []
    used_clauses, used_clause_literals = set(), set()
    used_paragraphs, used_paragraph_literals = set(), set()
    for ordinal, template in enumerate(TEMPLATES):
        members = []
        for key in _stratum_rules(rules, ordinal):
            text = sentence(template, rules[key])
            normal, literal = base._normal(text), text_sha(text)
            _require(normal not in forbidden and literal not in prior_literals
                     and normal not in used_clauses and literal not in used_clause_literals,
                     "normative TRAIN clause overlaps prior or generated source; complete generation refused")
            used_clauses.add(normal)
            used_clause_literals.add(literal)
            members.append((key, text))
        cursor = 0
        for count in (1, 2, 4, 8):
            for index in range(6):
                selected = members[cursor:cursor + count]
                cursor += count
                text = "\n\n".join(value for _, value in selected)
                normal, literal = base._normal(text), text_sha(text)
                identity = "normative-training-v1:" + literal
                _require(normal not in forbidden and literal not in prior_literals
                         and normal not in used_paragraphs and literal not in used_paragraph_literals
                         and identity not in prior_ids,
                         "normative TRAIN paragraph overlaps prior or generated source; complete generation refused")
                used_paragraphs.add(normal)
                used_paragraph_literals.add(literal)
                target = {"rules": [deepcopy(rules[key]) for key, _ in selected]}
                _require(len({tuple(rule[k] for k in ("actor", "action", "object"))
                              for rule in target["rules"]}) == count,
                         "conflicting content group in normative TRAIN paragraph")
                base._rules(target, validate_rule)
                ids = base._encode(target, codec)
                clause_ids = ["normative-training-clause-v1:" + text_sha(value) for _, value in selected]
                _require(not set(clause_ids).intersection(prior_ids),
                         "normative TRAIN clause identity overlaps prior inventory")
                paragraph_derivations = []
                for slot, ((key, value), clause_id) in enumerate(zip(selected, clause_ids)):
                    single = {"rules": [deepcopy(rules[key])]}
                    single_ids = base._encode(single, codec)
                    derivation = dict(rule_sha256=key, original_train_sources=deepcopy(derivations[key]))
                    paragraph_derivations.append(deepcopy(derivation))
                    clause_references.append(dict(
                        id=clause_id, source_text=value, source_sha256=text_sha(value),
                        split="train_augmentation", template=template,
                        modality_stratum=rules[key]["modality"],
                        parent_paragraph_id=identity, slot=slot,
                        target=single, target_ids=single_ids,
                        target_sha256=digest(single), target_ids_sha256=digest(single_ids),
                        original_rule_sha256=key, derivations=[derivation],
                        reference_origin="authored_rendering_of_original_TRAIN_rules", **FALSE))
                rows.append(dict(id=identity, source_text=text))
                references.append(dict(
                    id=identity, source_text=text, source_sha256=literal,
                    split="train_augmentation", template=template,
                    clause_count=count, index_within_template_length=index,
                    clause_ids=clause_ids, target=target, target_ids=ids,
                    target_sha256=digest(target), target_ids_sha256=digest(ids),
                    derivations=paragraph_derivations,
                    reference_origin="authored_rendering_of_original_TRAIN_rules", **FALSE))
        _require(cursor == len(members) == 90, "complete no-replacement stratum inventory required")
    counts = Counter(row["modality_stratum"] for row in clause_references)
    _require(len(rows) == len(references) == 48 and len(clause_references) == 180
             and len(used_clauses) == len(used_clause_literals) == 180
             and counts == {"O": 60, "P": 60, "F": 60}
             and Counter(row["clause_count"] for row in references) == {1: 12, 2: 12, 4: 12, 8: 12},
             "complete balanced normative TRAIN inventory required")
    templates = {template: [sentence(template, rules[key]) for key in sorted(rules)] for template in TEMPLATES}
    receipt = dict(
        schema=SCHEMA, complete=True, role="train_augmentation", seed=SEED,
        sealed_recipe_sha256=sealed_recipe_sha256, lifecycle_seal_verified=False,
        original_train_bank_sha256=digest(training_bank), original_train_sources=180,
        unique_original_train_rules=90, source_rows_sha256=digest(rows),
        references_sha256=digest(references), clause_references_sha256=digest(clause_references),
        codec_sha256=digest(codec), vocabulary_size=32,
        source_paragraphs=48, unique_clauses=180, clause_occurrences=180,
        single_clause_paragraph_aliases=12, unique_source_strings=216,
        templates=list(TEMPLATES), gerunds=deepcopy(GERUNDS),
        rendered_templates_sha256=digest(templates), prior_inventory=inventory,
        required_prior_datasets=list(REQUIRED_PRIOR_DATASETS),
        required_prior_row_counts=deepcopy(REQUIRED_PRIOR_COUNTS),
        prior_sources_sha256=digest(prior_sources_by_dataset),
        prior_inventory_completeness_verified=False,
        source_rows_contain_targets=False, original_target_roles_preserved=True,
        empty_qualifier_compatibility_verified=True,
        provenance="authored_rendering_of_original_TRAIN_rules",
        exclusion_policy="literal SHA256 and casefolded whitespace-normalized paragraphs and clauses",
        separation_claim="source-string exclusion only; no independent semantic holdout claim",
        paragraph_content_groups_unique=True,
        packing_policy="three rounds of one shuffled30-content-group order; initial modalities O/P/F",
        evaluation_labels_used=False, context_tokens=512, decoder_output_tokens=512,
        temperature=0, **FALSE)
    receipt["receipt_sha256"] = digest(receipt)
    return dict(source_rows=rows, references=references,
                clause_references=clause_references, receipt=receipt)
