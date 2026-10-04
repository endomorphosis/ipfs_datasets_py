"""Pure authored modality cohort with generic prior-source exclusions.

The caller authenticates every prior inventory and seals the experiment before
calling this builder. Neither a supplied seal nor a declared family partition
proves that lifecycle or linguistic novelty. References encode authored modal
assumptions only; syntax validation is not source-semantic or Lake admission.
No source files, parser, encoder, model, global RNG, or network are consulted.
"""
from collections import Counter
from copy import deepcopy
import re

from . import authored_scalar_holdout as base

SCHEMA = "authored-modality-holdout/v3"
FAMILIES = ("actor_normative_status", "norm_noun_subject", "gerund_normative_subject")
FAMILY_ROLES = ("training", "exposed", "evaluation")
ACTORS, ACTIONS, OBJECTS, MODALITIES = base.ACTORS, base.ACTIONS, base.OBJECTS, base.MODALITIES
VOCABULARY = base.VOCABULARY
FALSE = dict(base.FALSE)
digest, text_sha = base.digest, base.text_sha
_require = base._require
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _family_partition(family_roles):
    _require(type(family_roles) is dict and set(family_roles) == set(FAMILY_ROLES),
        "closed training/exposed/evaluation family roles required")
    used = set()
    for role in FAMILY_ROLES:
        names = family_roles[role]
        _require(type(names) is list and 1 <= len(names) <= 128
            and all(type(name) is str and _NAME.fullmatch(name) for name in names),
            "bounded nonempty lists of explicit family identities required")
        _require(len(names) == len(set(names)) and not used.intersection(names),
            "template family roles overlap or contain duplicates")
        used.update(names)
    _require(set(family_roles["evaluation"]) == set(FAMILIES),
        "evaluation must contain exactly the three fixed new families")


def _blacklist(prior_sources_by_dataset):
    _require(type(prior_sources_by_dataset) is dict and 1 <= len(prior_sources_by_dataset) <= 64
        and all(type(name) is str and _NAME.fullmatch(name) for name in prior_sources_by_dataset),
        "bounded explicitly named prior source inventories required")
    forbidden, prior_ids, reports, total_bytes = set(), {}, {}, 0
    for name, rows in prior_sources_by_dataset.items():
        _require(type(rows) is list and 1 <= len(rows) <= 4096,
            "each named prior source inventory must be a bounded nonempty list")
        identities, normalized, literals = set(), set(), set()
        for row in rows:
            text, pieces = base._source(row)
            _require(row["id"] not in identities, "duplicate source identity within a prior inventory")
            _require(row["id"] not in prior_ids or prior_ids[row["id"]] == text,
                "same prior source identity has conflicting literal text")
            identities.add(row["id"]); prior_ids[row["id"]] = text
            normalized.update(base._normal(item) for item in [text, *pieces])
            literals.update(text_sha(item) for item in [text, *pieces])
            total_bytes += len(text.encode("utf-8"))
            _require(total_bytes <= 16 * 1024**2, "prior source inventories exceed total byte bound")
        forbidden.update(normalized)
        reports[name] = dict(rows=len(rows), source_rows_sha256=digest(rows),
            normalized_paragraph_and_clause_count=len(normalized), literal_sha256_count=len(literals))
    return forbidden, set(prior_ids), reports


GERUNDS = dict(approve="approving", preserve="preserving", publish="publishing", examine="examining", deliver="delivering")


def _sentence(family, actor, action, object_, modality):
    gerund = GERUNDS[action]
    if family == "actor_normative_status":
        if modality == "F":
            return f"The {actor} is barred from {gerund} the {object_}."
        predicate = dict(O="obligated", P="authorized")[modality]
        return f"The {actor} is {predicate} to {action} the {object_}."
    if family == "norm_noun_subject":
        if modality == "F":
            return f"The prohibition is against the {actor} {gerund} the {object_}."
        noun = dict(O="obligation", P="permission")[modality]
        return f"The {noun} is for the {actor} to {action} the {object_}."
    _require(family == "gerund_normative_subject", "unknown fixed evaluation family")
    predicate = dict(O="an obligation of", P="authorized for", F="prohibited for")[modality]
    return f"{gerund.capitalize()} the {object_} is {predicate} the {actor}."


def build_holdout(*, training_rows, prior_sources_by_dataset, family_roles, codec,
                  sealed_comparison_sha256, seed=20261006, validate_rule):
    """Return separate 48 source paragraphs, authored references, and a receipt.

    Training rows are closed ``{id,source_text,target}`` records. Arbitrarily
    named prior inventories contain only closed ``{id,source_text}`` records;
    supply every old split, exposed cohort, and any new training paraphrases.
    Their syntax is unrestricted. ``family_roles`` declares disjoint nonempty
    ``training``, ``exposed``, and ``evaluation`` identity lists. This declaration
    does not infer families from text or prove that all prior data were supplied.
    """
    base._codec(codec)
    _require(type(seed) is int and 0 <= seed <= 2**31 - 1, "bounded nonboolean seed required")
    _require(type(sealed_comparison_sha256) is str and base._SHA.fullmatch(sealed_comparison_sha256),
        "explicit sealed comparison SHA256 required")
    _require(callable(validate_rule), "explicit syntax validator required")
    _require(type(training_rows) is list and 1 <= len(training_rows) <= 128,
        "bounded complete training rows required")
    _family_partition(family_roles)
    forbidden, prior_ids, blacklist_reports = _blacklist(prior_sources_by_dataset)
    train_ids, train_literals, source_labels, seen = set(), set(), {}, set()
    for row in training_rows:
        text, pieces = base._source(row, training=True)
        _require(row["id"] not in train_ids and base._normal(text) not in train_literals,
            "duplicate training identity or normalized paragraph")
        train_ids.add(row["id"]); train_literals.add(base._normal(text))
        target = row["target"]
        base._rules(target, validate_rule); base._encode(target, codec)
        _require(len(pieces) == len(target["rules"]), "training literal clause/rule count differs")
        for piece, rule in zip(pieces, target["rules"]):
            key = base._normal(piece)
            _require(key in forbidden, "training clause absent from explicit prior inventories")
            _require(key not in source_labels or source_labels[key] == rule,
                "same training source has conflicting reference labels")
            source_labels[key] = rule
            seen.add((rule["actor"], rule["action"]))
        forbidden.add(base._normal(text))
    matchings = base._matching_decomposition(seen, 3, seed, "training_seen")
    unseen = {(a, b) for a in ACTORS for b in ACTIONS} - seen
    unseen_matchings = base._matching_decomposition(unseen, 2, seed, "training_unseen")
    source_rows, references, family_reports = [], [], []
    used_literals, used_paragraphs = set(), set()
    counterfactual_groups = {}
    for family_index, family in enumerate(FAMILIES):
        pairs = [*matchings[family_index], *unseen_matchings[family_index % 2]]
        clauses = []
        for actor, action in pairs:
            for object_ in OBJECTS:
                group = "authored-modality-group:" + digest([family, actor, action, object_])
                counterfactual_groups[group] = []
                for modality in MODALITIES:
                    sentence = _sentence(family, actor, action, object_, modality)
                    normalized = base._normal(sentence)
                    _require(normalized not in forbidden and normalized not in used_literals,
                        "new literal overlaps prior blacklist or another authored clause")
                    used_literals.add(normalized)
                    rule = dict(actor=actor, action=action, object=object_, modality=modality,
                                conditions=[], exceptions=[], temporal=[])
                    base._rules({"rules": [rule]}, validate_rule)
                    counterfactual_groups[group].append(modality)
                    clauses.append(dict(source_text=sentence, source_sha256=text_sha(sentence),
                        rule=rule, training_pair_seen=(actor, action) in seen,
                        counterfactual_group_id=group))
        for count, index, members in base._compose(clauses, family, seed):
            source = "\n\n".join(item["source_text"] for item in members)
            _require(base._normal(source) not in forbidden and base._normal(source) not in used_paragraphs,
                "new paragraph overlaps prior blacklist or another paragraph")
            used_paragraphs.add(base._normal(source))
            identity = "fresh-modality-v3:" + text_sha(source)
            _require(identity not in prior_ids and identity not in train_ids, "new identity overlaps prior source")
            target = {"rules": [deepcopy(item["rule"]) for item in members]}
            components, offset = [], 0
            for slot, item in enumerate(members):
                end = offset + len(item["source_text"])
                components.append(dict(slot=slot, source_sha256=item["source_sha256"],
                    char_start=offset, char_end=end, byte_start=len(source[:offset].encode()),
                    byte_end=len(source[:end].encode()), training_pair_seen=item["training_pair_seen"],
                    counterfactual_group_id=item["counterfactual_group_id"]))
                offset = end + 2
            source_rows.append(dict(id=identity, source_text=source))
            references.append(dict(id=identity, source_text=source, source_sha256=text_sha(source),
                split="fresh_authored_holdout", group_id=family, template_family=family,
                clause_count=count, index_within_family_length=index, target=target,
                target_sha256=digest(target), target_ids=base._encode(target, codec),
                components=components, codec_sha256=digest(codec),
                reference_origin="authored literal clause ordinal to rule ordinal; review pending", **FALSE))
        family_reports.append(dict(template_family=family, paragraph_count=16, clause_occurrences=60,
            training_seen_pairs=[list(pair) for pair in matchings[family_index]],
            training_unseen_pairs=[list(pair) for pair in unseen_matchings[family_index % 2]],
            training_seen_clause_occurrences=30, training_unseen_clause_occurrences=30,
            counterfactual_triplets=20,
            actor_counts=dict(Counter(item["rule"]["actor"] for item in clauses)),
            action_counts=dict(Counter(item["rule"]["action"] for item in clauses)),
            object_counts=dict(Counter(item["rule"]["object"] for item in clauses)),
            modality_counts=dict(Counter(item["rule"]["modality"] for item in clauses))))
    _require(len(source_rows) == 48 and len(used_literals) == 180
        and len(counterfactual_groups) == 60
        and all(v == list(MODALITIES) for v in counterfactual_groups.values()),
        "fixed complete source or counterfactual inventory differs")
    receipt = dict(schema=SCHEMA, complete=True, seed=seed, split="fresh_authored_holdout",
        sealed_comparison_sha256=sealed_comparison_sha256, comparison_seal_verified=False,
        training_rows_sha256=digest(training_rows),
        prior_sources_by_dataset_sha256=digest(prior_sources_by_dataset),
        prior_dataset_inventory=blacklist_reports, family_roles=deepcopy(family_roles),
        family_roles_sha256=digest(family_roles), codec_sha256=digest(codec), full_vocabulary_size=32,
        source_rows_sha256=digest(source_rows), references_sha256=digest(references),
        paragraph_count=48, clause_occurrences=180, unique_clauses=180, counterfactual_triplets=60,
        paragraph_counts_by_length=dict(Counter(str(row["clause_count"]) for row in references)),
        training_seen_pairs=[list(pair) for pair in sorted(seen)],
        training_unseen_pairs=[list(pair) for pair in sorted(unseen)], family_reports=family_reports,
        source_join="two literal newline characters", source_rows_contain_targets=False,
        family_split_policy="declared disjoint training/exposed/evaluation families; all new families postfit-only",
        prior_template_policy="generic literal source exclusion; no prior syntax recognition or parser fallback",
        template_separation_scope="declared authored construction families, not linguistic equivalence proof",
        authored_modal_assumption="obligated/obligation encode O; authorized/permission encode P; barred/prohibition/prohibited encode F; all clauses are authored normative assertions",
        source_exclusion_policy="casefold whitespace-normalized paragraphs and literal clauses against every supplied named inventory",
        target_provenance="authored fixed lexical contract; supplied syntax validator only",
        input_authenticity_scope="caller-authenticated complete prior inventories and experiment lifecycle required",
        prior_inventory_completeness_verified=False, family_assignment_inferred_from_text=False,
        evaluation_policy="compare all sealed arms once after fitting; do not select or update on this cohort",
        expected_unique_encoder_sources=216, encoder_context_tokens=512, decoder_output_tokens=512,
        encoder_token_limit_checked=False, decoder_target_limit_checked=True, **FALSE)
    receipt["receipt_sha256"] = digest(receipt)
    return dict(source_rows=source_rows, references=references, receipt=receipt)


__all__ = ["build_holdout", "FAMILIES", "FAMILY_ROLES"]
