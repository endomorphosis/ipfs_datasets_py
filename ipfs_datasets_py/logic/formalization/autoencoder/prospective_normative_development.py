"""Pure prospective source wording over the complete original validation bank.

References retain previously exposed authored meanings. This is a wording-only
development panel, never independent semantic evidence, TRAIN, or Lake admission.
The caller authenticates inputs and seals this recipe before model execution.
No parser, encoder, checkpoint, file, network, or global RNG is consulted here.
"""
from collections import Counter
from copy import deepcopy
import json

from . import authored_scalar_holdout as base
from . import authored_modality_holdout_v3 as prior

SCHEMA = "prospective-normative-development/v1"
ROLE = "prospective_authored_development"
TEMPLATES = ("normative_that_clause_v1", "actor_norm_possession_v1")
TEMPLATE_TEXT = {
    TEMPLATES[0]: {
        "O": "It is mandatory that the {actor} {action} the {object}.",
        "P": "It is permissible that the {actor} {action} the {object}.",
        "F": "It is prohibited that the {actor} {action} the {object}.",
    },
    TEMPLATES[1]: {
        "O": "The {actor} bears a duty to {action} the {object}.",
        "P": "The {actor} holds permission to {action} the {object}.",
        "F": "The {actor} faces a ban on {gerund} the {object}.",
    },
}
GERUNDS = dict(approve="approving", preserve="preserving", publish="publishing",
               examine="examining", deliver="delivering")
REQUIRED_PRIOR_DATASETS = (
    "exposed_r6", "exposed_r8", "exposed_v3", "original_train_bank",
    "paragraph_train", "paragraph_validation", "raw_canary", "raw_test",
    "raw_train", "raw_validation", "r4_training_paraphrases", "composition64",
    "new_training_wordings",
)
FALSE = dict(admitted=False, qualified=False, formalized=False, roundtrip_ok=False,
    proof_authority=False, lake_executed=False, source_semantics_verified=False,
    source_alignment_reviewed=False, training_executed=False, encoder_executed=False,
    checkpoint_promoted=False, historical_linguistic_teacher_modified=False,
    fresh_holdout_claimed=False, training_allowed=False, selection_allowed=False)
digest = base.digest
_require = base._require


def recipe():
    """Return the complete fixed wording policy for an external lifecycle seal."""
    return dict(schema=SCHEMA, role=ROLE, templates=list(TEMPLATES),
        template_text=deepcopy(TEMPLATE_TEXT), gerunds=deepcopy(GERUNDS),
        original_validation_sources=60, unique_original_validation_rules=30,
        source_rows=60, clauses_per_source=1, modalities=dict(O=20, P=20, F=20),
        required_prior_datasets=list(REQUIRED_PRIOR_DATASETS),
        ordering="template ordinal then canonical original-rule SHA256",
        reference_origin="authored rendering of previously exposed original validation rules",
        actor_action_groups_disjoint_from_train_required=True,
        qualifiers="all seven fields preserved; nonempty qualifiers refused",
        exclusion="literal and case-folded whitespace-normalized paragraphs and clauses",
        encoder_context_tokens=512, decoder_output_tokens=512, temperature=0,
        **FALSE)


def sentence(template, rule):
    """Render one checked restricted rule without introducing qualifiers."""
    _require(template in TEMPLATES and type(rule) is dict
        and set(rule) == base._RULE_KEYS, "complete fixed development rule required")
    actor, action, obj, modality = (rule[k] for k in ("actor", "action", "object", "modality"))
    _require(actor in base.ACTORS and action in base.ACTIONS and obj in base.OBJECTS
        and modality in base.MODALITIES
        and all(type(rule[k]) is list and not rule[k]
                for k in ("conditions", "exceptions", "temporal")),
        "development renderer cannot drop a qualifier or extend lexical inventory")
    return TEMPLATE_TEXT[template][modality].format(actor=actor, action=action,
        object=obj, gerund=GERUNDS[action])


def _bank(rows, *, role, codec, validate_rule):
    development = role == "validation"
    expected_rows, expected_rules = (60, 30) if development else (180, 90)
    _require(type(rows) is list and len(rows) == expected_rows,
        "complete original " + role + " bank required")
    identities, sources, rules, derivations = set(), set(), {}, {}
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text", "target_ids"},
            "closed original bank row required; vectors and predictions forbidden")
        text, pieces = base._source({k: row[k] for k in ("id", "source_text")})
        _require(len(pieces) == 1 and row["id"] not in identities
            and base._normal(text) not in sources,
            "unique single-clause original identities and sources required")
        identities.add(row["id"]); sources.add(base._normal(text))
        ids = row["target_ids"]
        _require(type(ids) is list and 3 <= len(ids) <= 512
            and all(type(i) is int for i in ids) and ids[0] == 1 and ids[-1] == 2
            and all(3 <= i < 32 for i in ids[1:-1]), "complete original 32V target required")
        target = json.loads("".join(codec["target_vocabulary"][i] for i in ids[1:-1]))
        base._rules(target, validate_rule)
        _require(len(target["rules"]) == 1 and base._encode(target, codec) == ids,
            "canonical single-rule original target required")
        rule = target["rules"][0]; key = digest(rule)
        _require(key not in rules or rules[key] == rule, "original rule digest collision")
        rules[key] = deepcopy(rule)
        derivations.setdefault(key, []).append(dict(id=row["id"],
            source_sha256=base.text_sha(text), target_sha256=digest(target),
            target_ids_sha256=digest(ids)))
    _require(len(rules) == expected_rules and all(len(v) == 2 for v in derivations.values()),
        "complete original bank needs two renderings for every unique rule")
    per_actor, per_modality, per_object = (6, 10, 15) if development else (18, 30, 45)
    expected = {"actor": dict.fromkeys(base.ACTORS, per_actor),
        "action": dict.fromkeys(base.ACTIONS, per_actor),
        "object": dict.fromkeys(base.OBJECTS, per_object),
        "modality": dict.fromkeys(base.MODALITIES, per_modality)}
    for field, wanted in expected.items():
        _require(Counter(r[field] for r in rules.values()) == wanted,
            "original " + role + " field balance differs: " + field)
    pairs = {(r["actor"], r["action"]) for r in rules.values()}
    _require(len(pairs) == (5 if development else 15)
        and len({(r["actor"], r["action"], r["object"], r["modality"])
                 for r in rules.values()}) == expected_rules,
        "complete original actor/action/object/modality product required")
    return rules, derivations, pairs


def build(*, validation_bank, training_bank, prior_sources_by_dataset, codec,
          sealed_recipe_sha256, validate_rule):
    """Build all 60 single-clause sources and separate development references.

    Banks are closed ``{id, source_text, target_ids}`` records. Named exclusion
    inventories contain only closed ``{id, source_text}`` rows. Required prior
    names enforce declared scope, not authenticity or comprehensive discovery.
    Any count, qualifier, group overlap, or text collision refuses the whole
    generation. No surviving subset is selected and no target is inferred.
    """
    base._codec(codec)
    _require(callable(validate_rule), "explicit syntax validator required")
    _require(type(sealed_recipe_sha256) is str and base._SHA.fullmatch(sealed_recipe_sha256),
        "explicit externally sealed recipe SHA256 required")
    _require(type(prior_sources_by_dataset) is dict
        and set(REQUIRED_PRIOR_DATASETS) <= set(prior_sources_by_dataset),
        "all declared prior source inventories, new TRAIN, and composition64 required")
    rules, derivations, validation_pairs = _bank(validation_bank, role="validation",
        codec=codec, validate_rule=validate_rule)
    _, _, training_pairs = _bank(training_bank, role="train", codec=codec, validate_rule=validate_rule)
    _require(not validation_pairs.intersection(training_pairs),
        "prospective development actor/action groups overlap original TRAIN")
    _require(not {r['id'] for r in validation_bank}.intersection(r['id'] for r in training_bank),
        "original validation and TRAIN source identities overlap")
    forbidden, prior_ids, inventory = prior._blacklist(prior_sources_by_dataset)
    for name, bank in (("raw_validation", validation_bank), ("original_train_bank", training_bank)):
        supplied = {r['id']: r['source_text'] for r in prior_sources_by_dataset[name]}
        _require(all(supplied.get(r['id']) == r['source_text'] for r in bank),
            "original bank identity/text absent from its declared prior inventory: " + name)
    rows, references, literals, normalized = [], [], set(), set()
    for template in TEMPLATES:
        for key in sorted(rules):
            rule = rules[key]; text = sentence(template, rule)
            identity = "prospective-normative-v1:" + base.text_sha(text)
            _require(base._normal(text) not in forbidden and base._normal(text) not in normalized
                and base.text_sha(text) not in literals and identity not in prior_ids,
                "prospective development wording overlaps prior or generated source")
            normalized.add(base._normal(text)); literals.add(base.text_sha(text))
            target = {"rules": [deepcopy(rule)]}; ids = base._encode(target, codec)
            base._rules(target, validate_rule)
            rows.append(dict(id=identity, source_text=text))
            references.append(dict(id=identity, source_text=text, split=ROLE,
                template=template, clause_count=1, target=target, target_ids=ids,
                source_sha256=base.text_sha(text), target_sha256=digest(target),
                target_ids_sha256=digest(ids), derivations=[dict(rule_sha256=key,
                    original_validation_sources=deepcopy(derivations[key]))],
                reference_origin="authored rendering of previously exposed original validation rules",
                label_provenance="authored_development", original_meanings_previously_exposed=True,
                prospective_wording_lifecycle_verified=False, **FALSE))
    _require(len(rows) == len(references) == len(literals) == len(normalized) == 60
        and Counter(r['target']['rules'][0]['modality'] for r in references) == {"O":20,"P":20,"F":20},
        "complete balanced prospective development generation required")
    receipt = dict(schema=SCHEMA, complete=True, role=ROLE,
        recipe_sha256=digest(recipe()), sealed_recipe_sha256=sealed_recipe_sha256,
        lifecycle_seal_verified=False, original_validation_bank_sha256=digest(validation_bank),
        original_train_bank_sha256=digest(training_bank), original_validation_sources=60,
        original_train_sources=180, unique_original_validation_rules=30,
        source_rows=60, source_clauses=60, templates=list(TEMPLATES),
        modality_counts=dict(O=20,P=20,F=20), source_rows_sha256=digest(rows),
        references_sha256=digest(references), codec_sha256=digest(codec), vocabulary_size=32,
        validation_actor_action_groups=[list(x) for x in sorted(validation_pairs)],
        original_train_actor_action_groups=[list(x) for x in sorted(training_pairs)],
        actor_action_group_overlap=0, actor_action_disjointness_checked=True,
        prior_inventory=inventory, prior_sources_sha256=digest(prior_sources_by_dataset),
        prior_inventory_completeness_verified=False, source_rows_contain_targets=False,
        literal_overlap=0, normalized_overlap=0,
        label_provenance="authored_development", original_meanings_previously_exposed=True,
        exposure_policy="sealed wording before fit; postfit measurements only; no selection or TRAIN use",
        linguistic_novelty_claimed=False, independent_human_review_authenticated=False,
        qualifiers_empty_floor=True, context_tokens=512, decoder_output_tokens=512,
        temperature=0, **FALSE)
    receipt['receipt_sha256'] = digest(receipt)
    return dict(source_rows=rows, references=references, receipt=receipt)
