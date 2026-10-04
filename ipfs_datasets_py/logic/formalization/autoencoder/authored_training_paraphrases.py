"""Training-only authored renderings of authenticated original TRAIN rules.

No parser, encoder, checkpoint or network is consulted. The caller authenticates
the bank and all prior-source inventories. Syntax checks and authored alignment
do not establish semantic correctness or give Lake admission. Some renderings
extend exposed constructions; only literal separation is claimed.
"""
from collections import Counter
from copy import deepcopy
import json
import random

from . import authored_scalar_holdout as base
from . import authored_modality_holdout_v3 as prior

SCHEMA = "authored-training-paraphrases/v1"
TEMPLATES = ("rule_gerund_by_actor", "topicalized_actor_norm")
FALSE = dict(admitted=False, qualified=False, formalized=False, roundtrip_ok=False,
    proof_authority=False, lake_executed=False, source_semantics_verified=False,
    training_executed=False, encoder_executed=False, checkpoint_promoted=False,
    historical_linguistic_teacher_modified=False, fresh_holdout_claimed=False)
digest = base.digest
_require = base._require


def sentence(template, rule):
    actor, action, obj, modality = (rule[k] for k in ("actor", "action", "object", "modality"))
    _require(template in TEMPLATES and actor in base.ACTORS and action in base.ACTIONS
        and obj in base.OBJECTS and modality in base.MODALITIES, "closed authored lexical inventory required")
    gerund = prior.GERUNDS[action]
    if template == TEMPLATES[0]:
        verb = dict(O="requires", P="permits", F="forbids")[modality]
        return f"The rule {verb} {gerund} the {obj} by the {actor}."
    predicate = dict(O="required", P="permitted", F="forbidden")[modality]
    return f"For the {actor}, {gerund} the {obj} is {predicate} by the rule."


def _bank(rows, codec, validate_rule):
    base._codec(codec)
    _require(callable(validate_rule) and type(rows) is list and len(rows) == 180,
        "complete original180 TRAIN bank and syntax validator required")
    identities, sources, rules, derivations = set(), set(), {}, {}
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text", "target_ids"},
            "closed original TRAIN row required; no vectors or evaluation fields")
        text, pieces = base._source({k: row[k] for k in ("id", "source_text")})
        _require(len(pieces) == 1 and row["id"] not in identities
            and base._normal(text) not in sources, "unique single-clause original TRAIN identities required")
        identities.add(row["id"]); sources.add(base._normal(text))
        ids = row["target_ids"]
        _require(type(ids) is list and 3 <= len(ids) <= 512 and all(type(i) is int for i in ids) and ids[0] == 1 and ids[-1] == 2
            and all(type(i) is int and 3 <= i < 32 for i in ids[1:-1]), "complete original32V target required")
        target = json.loads("".join(codec["target_vocabulary"][i] for i in ids[1:-1]))
        base._rules(target, validate_rule)
        _require(len(target["rules"]) == 1 and base._encode(target, codec) == ids,
            "canonical single-rule original target required")
        rule = target["rules"][0]; key = digest(rule)
        _require(key not in rules or rules[key] == rule, "rule digest collision")
        rules[key] = deepcopy(rule)
        derivations.setdefault(key, []).append(dict(id=row["id"], source_sha256=base.text_sha(text),
            target_sha256=digest(target), target_ids_sha256=digest(ids)))
    _require(len(rules) == 90 and all(len(v) == 2 for v in derivations.values()),
        "original TRAIN must have exactly90 rules with two source renderings each")
    expected = {"actor": dict.fromkeys(base.ACTORS, 18), "action": dict.fromkeys(base.ACTIONS, 18),
        "object": dict.fromkeys(base.OBJECTS, 45), "modality": dict.fromkeys(base.MODALITIES, 30)}
    for field, wanted in expected.items():
        _require(Counter(r[field] for r in rules.values()) == wanted, "original TRAIN field balance differs: "+field)
    pairs = {(r["actor"], r["action"]) for r in rules.values()}
    _require(len(pairs) == 15 and len({(r["actor"], r["action"], r["object"], r["modality"])
        for r in rules.values()}) == 90, "complete TRAIN pair/modality/object product required")
    return rules, derivations


def build(*, training_bank, prior_sources_by_dataset, codec, sealed_recipe_sha256,
          validate_rule, seed=20261007):
    """Return separately stored source rows and TRAIN-derived references.

    Every original rule appears once per template. No candidate is filtered or
    replaced when exclusion fails. The caller's digest is a binding, not proof
    that a recipe was sealed before seeing model scores.
    """
    _require(type(seed) is int and 0 <= seed < 2**31, "bounded nonboolean seed required")
    _require(type(sealed_recipe_sha256) is str and base._SHA.fullmatch(sealed_recipe_sha256),
        "explicit sealed recipe digest required")
    rules, derivations = _bank(training_bank, codec, validate_rule)
    forbidden, prior_ids, inventory = prior._blacklist(prior_sources_by_dataset)
    _require(all(base._normal(row["source_text"]) in forbidden for row in training_bank),
        "original TRAIN source missing from explicit prior inventories")
    rows, references, used_clauses, used_paragraphs = [], [], set(), set()
    for family_index, template in enumerate(TEMPLATES):
        # Thirty content groups, each with O/P/F. Reuse one shuffled group order
        # across three rounds so variants of a content group are exactly thirty
        # positions apart. Every contiguous paragraph (at most eight clauses)
        # consequently has no unexplained conflicting norms for one content.
        groups = {}
        for key, rule in rules.items():
            group = tuple(rule[k] for k in ('actor', 'action', 'object'))
            groups.setdefault(group, []).append(key)
        _require(len(groups) == 30 and all(len(v) == 3 for v in groups.values()),
            'complete three-modality content groups required')
        rng = random.Random(seed+family_index)
        ordered = sorted(groups); rng.shuffle(ordered)
        for group in ordered:
            groups[group].sort(); rng.shuffle(groups[group])
        keys = [groups[group][round_] for round_ in range(3) for group in ordered]
        clauses = []
        for key in keys:
            text = sentence(template, rules[key]); normalized = base._normal(text)
            _require(normalized not in forbidden and normalized not in used_clauses,
                "training paraphrase overlaps prior or generated clause")
            used_clauses.add(normalized); clauses.append((key, text))
        cursor = 0
        for count in (1, 2, 4, 8):
            for ordinal in range(6):
                members = clauses[cursor:cursor+count]; cursor += count
                text = "\n\n".join(t for _, t in members); normalized = base._normal(text)
                identity = "authored-training-v1:"+base.text_sha(text)
                _require(normalized not in forbidden and normalized not in used_paragraphs
                    and identity not in prior_ids, "training paragraph overlaps prior or generated source")
                used_paragraphs.add(normalized)
                target = {"rules": [deepcopy(rules[key]) for key, _ in members]}
                _require(len({tuple(r[k] for k in ('actor', 'action', 'object'))
                    for r in target['rules']}) == count, 'conflicting content group in training paragraph')
                ids = base._encode(target, codec); base._rules(target, validate_rule)
                rows.append(dict(id=identity, source_text=text))
                references.append(dict(id=identity, source_text=text, split="train_augmentation",
                    template=template, clause_count=count, index_within_template_length=ordinal,
                    target=target, target_ids=ids, target_sha256=digest(target),
                    derivations=[dict(rule_sha256=key, original_train_sources=deepcopy(derivations[key]))
                        for key, _ in members], reference_origin="authored rendering of original TRAIN rules", **FALSE))
        _require(cursor == len(clauses) == 90, "complete no-replacement template inventory required")
    _require(len(rows) == 48 and len(used_clauses) == 180
        and Counter(r["clause_count"] for r in references) == {1:12, 2:12, 4:12, 8:12},
        "complete balanced paragraph inventory required")
    template_texts = {name: [sentence(name, rules[key]) for key in sorted(rules)] for name in TEMPLATES}
    receipt = dict(schema=SCHEMA, complete=True, role="train_augmentation", seed=seed,
        sealed_recipe_sha256=sealed_recipe_sha256, lifecycle_seal_verified=False,
        original_train_bank_sha256=digest(training_bank), original_train_sources=180,
        unique_original_train_rules=90, source_rows_sha256=digest(rows), references_sha256=digest(references),
        codec_sha256=digest(codec), vocabulary_size=32, source_paragraphs=48, unique_clauses=180,
        templates=list(TEMPLATES), rendered_templates_sha256=digest(template_texts),
        prior_inventory=inventory, prior_sources_sha256=digest(prior_sources_by_dataset),
        prior_inventory_completeness_verified=False, source_rows_contain_targets=False,
        separation_claim="literal and normalized-source exclusion only; some constructions extend exposed styles",
        paragraph_content_groups_unique=True, packing_policy="three rounds of one shuffled30-content-group order",
        evaluation_labels_used=False, context_tokens=512, decoder_output_tokens=512, temperature=0, **FALSE)
    receipt["receipt_sha256"] = digest(receipt)
    return dict(source_rows=rows, references=references, receipt=receipt)
