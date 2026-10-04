"""Pure, fixed-vocabulary authored holdout preparation; no models or imports.

New syntactic families remain postfit-only. The caller must authenticate the
training/blacklist files and enforce the comparison seal before exposing these
references. A digest supplied to this function does not prove that lifecycle.
Authored alignment and syntax validation are not semantic or Lake admission.
"""
from collections import Counter
from copy import deepcopy
import hashlib
from itertools import permutations
import json
import re

SCHEMA = "authored-scalar-holdout/v1"
ACTORS = ("registrar", "trustee", "secretary", "treasurer", "notary")
ACTIONS = ("approve", "preserve", "publish", "examine", "deliver")
OBJECTS = ("notice", "archive")
MODALITIES = ("O", "P", "F")
FAMILIES = ("passive_normative", "actor_topicalized_gerund", "nominal_normative")
PRIOR_SPLITS = ("train", "validation", "test", "canary")
VOCABULARY = ['<pad>', '<bos>', '<eos>', '"F"', '"O"', '"P"', '"action"',
    '"actor"', '"approve"', '"archive"', '"conditions"', '"deliver"', '"examine"',
    '"exceptions"', '"modality"', '"notary"', '"notice"', '"object"', '"preserve"',
    '"publish"', '"registrar"', '"rules"', '"secretary"', '"temporal"',
    '"treasurer"', '"trustee"', ',', ':', '[', ']', '{', '}']
_RULE_KEYS = {"actor", "action", "modality", "object", "conditions", "exceptions", "temporal"}
_TOKEN = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"|[{}\[\],:]')
_SHA = re.compile(r"[0-9a-f]{64}\Z")
FALSE = dict(admitted=False, qualified=False, formalized=False, roundtrip_ok=False,
    proof_authority=False, source_semantics_verified=False, source_alignment_reviewed=False,
    lake_executed=False, training_executed=False, embedding_inference_executed=False,
    historical_linguistic_teacher_modified=False, training_allowed=False,
    selection_allowed=False, holdout_evaluated=False, fresh_holdout_claimed=False)


def _require(value, message):
    if not value:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normal(text):
    return " ".join(text.casefold().split())


def _old_template(text):
    """Conservative recognition of the exact prior v2 authored syntax only."""
    normalized = _normal(text)
    templates = []
    for prefix in ("", "by policy, "):
        for modal in (("must", "may", "must not") if prefix else
                      ("must", "may", "must not", "is required to", "is allowed to", "is forbidden to")):
            pattern = re.escape(prefix + "the ") + "(" + "|".join(ACTORS) + ") " + re.escape(modal)
            pattern += " (" + "|".join(ACTIONS) + ") the (" + "|".join(OBJECTS) + r")\."
            if re.fullmatch(pattern, normalized):
                templates.append(prefix + "the {actor} " + modal + " {action} the {object}.")
    _require(len(templates) == 1,
        "prior clause has unreviewed syntactic template; cannot establish new-family separation")
    return templates[0]


def _codec(codec):
    _require(type(codec) is dict and set(codec) == {"schema", "target_vocabulary"}
        and codec["schema"] == "typed-json-lexical/v1"
        and type(codec["target_vocabulary"]) is list and codec["target_vocabulary"] == VOCABULARY,
        "exact unchanged 32-token Legal codec required")


def _encode(target, codec):
    wire = raw(target).decode("utf-8")
    tokens = _TOKEN.findall(wire)
    _require("".join(tokens) == wire and all(token in VOCABULARY for token in tokens),
        "complete target outside original vocabulary")
    ids = [1] + [codec["target_vocabulary"].index(token) for token in tokens] + [2]
    _require(len(ids) <= 512 and json.loads("".join(VOCABULARY[i] for i in ids[1:-1])) == target,
        "complete lexical target exceeds output limit or lost content")
    return ids


def _source(row, *, training=False):
    keys = {"id", "source_text", "target"} if training else {"id", "source_text"}
    _require(type(row) is dict and set(row) == keys, "closed training or source-only row required")
    _require(type(row["id"]) is str and 0 < len(row["id"]) <= 1024,
        "bounded source identity required")
    text = row["source_text"]
    _require(type(text) is str and text.strip() and len(text.encode("utf-8")) <= 32768,
        "bounded nonempty literal source required")
    clauses = text.split("\n\n")
    _require(all(clause.strip() for clause in clauses), "empty literal source clause")
    return text, clauses


def _rules(target, validate_rule):
    _require(type(target) is dict and set(target) == {"rules"}
        and type(target["rules"]) is list and 1 <= len(target["rules"]) <= 8,
        "one to eight complete authored rules required")
    for rule in target["rules"]:
        _require(type(rule) is dict and set(rule) == _RULE_KEYS
            and type(rule["actor"]) is str and rule["actor"] in ACTORS
            and type(rule["action"]) is str and rule["action"] in ACTIONS
            and type(rule["object"]) is str and rule["object"] in OBJECTS
            and type(rule["modality"]) is str and rule["modality"] in MODALITIES
            and all(type(rule[k]) is list and not rule[k] for k in ("conditions", "exceptions", "temporal")),
            "complete rule outside fixed scalar coverage; no repair or dropped facets")
        supplied = {"rules": [deepcopy(rule)]}
        before = raw(supplied)
        result = validate_rule(supplied)
        _require(raw(supplied) == before, "supplied syntax validator mutated target")
        _require(type(result) is dict and result.get("valid") is True
            and ("canonical_ir" not in result or raw(result["canonical_ir"]) == before),
            "supplied single-rule syntax validation failed or changed target")


def _matching_decomposition(edges, degree, seed, role):
    """Deterministic perfect matchings of a checked regular bipartite graph."""
    edges = set(edges)
    _require(len(edges) == 5 * degree
        and all(sum(a == actor for a, _ in edges) == degree for actor in ACTORS)
        and all(sum(b == action for _, b in edges) == degree for action in ACTIONS),
        "training actor-action graph must have exact balanced degree three")
    result = []
    for position in range(degree):
        possible = [tuple(zip(ACTORS, order)) for order in permutations(ACTIONS)
                    if all(pair in edges for pair in zip(ACTORS, order))]
        _require(possible, "balanced graph has no complete matching")
        chosen = min(possible, key=lambda pairs: digest([seed, role, position, pairs]))
        result.append(chosen)
        edges.difference_update(chosen)
    _require(not edges, "matching decomposition lost pairs")
    return result


def _sentence(family, actor, action, object_, modality):
    past = dict(approve="approved", preserve="preserved", publish="published",
                examine="examined", deliver="delivered")[action]
    gerund = dict(approve="approving", preserve="preserving", publish="publishing",
                  examine="examining", deliver="delivering")[action]
    if family == "passive_normative":
        modal = dict(O="must be", P="may be", F="must not be")[modality]
        return f"The {object_} {modal} {past} by the {actor}."
    if family == "actor_topicalized_gerund":
        predicate = dict(O="obligatory", P="permitted", F="prohibited")[modality]
        return f"For the {actor}, {gerund} the {object_} is {predicate}."
    _require(family == "nominal_normative", "unknown fixed syntactic family")
    predicate = dict(O="has a duty to " + action, P="has permission to " + action,
                     F="is under a prohibition against " + gerund)[modality]
    return f"The {actor} {predicate} the {object_}."


def _compose(clauses, family, seed):
    by_slot = {}
    for clause in clauses:
        slot = tuple(clause["rule"][k] for k in ("actor", "action", "object"))
        by_slot.setdefault(slot, []).append(clause)
    result = []
    # Largest bins first, giving precedence to slots with most remaining uses.
    for count in (8, 4, 2, 1):
        for index in range(4):
            candidates = [slot for slot, values in by_slot.items() if values]
            chosen = sorted(candidates, key=lambda slot: (-len(by_slot[slot]),
                digest([seed, family, count, index, slot])))[:count]
            _require(len(chosen) == count, "fixed complete paragraph assignment unavailable")
            members = []
            for slot in chosen:
                value = min(by_slot[slot], key=lambda item: digest([seed, family, count, index, item]))
                by_slot[slot].remove(value)
                members.append(value)
            result.append((count, index, members))
    _require(all(not values for values in by_slot.values()), "paragraph assignment omitted source clauses")
    return sorted(result, key=lambda item: item[:2])


def build_holdout(*, training_rows, prior_sources_by_split, codec,
                  sealed_comparison_sha256, seed=20261004, validate_rule):
    """Build 48 postfit-only paragraphs and separate reference targets.

    ``training_rows`` are closed ``{id,source_text,target}`` records. The four
    prior split lists are closed ``{id,source_text}`` literal blacklists, not
    reference targets. Input authenticity and the comparison's lifecycle are
    the caller's responsibility; all supplied inputs are bound in the receipt.
    No target, family or count is attached to returned ``source_rows``.
    """
    _codec(codec)
    _require(type(seed) is int and 0 <= seed <= 2**31 - 1, "bounded nonboolean seed required")
    _require(type(sealed_comparison_sha256) is str and _SHA.fullmatch(sealed_comparison_sha256),
        "explicit sealed comparison SHA256 required")
    _require(callable(validate_rule), "explicit syntax validator required")
    _require(type(training_rows) is list and 1 <= len(training_rows) <= 128,
        "bounded complete training rows required")
    _require(type(prior_sources_by_split) is dict and set(prior_sources_by_split) == set(PRIOR_SPLITS),
        "all four explicit prior split literal blacklists required")
    forbidden, blacklists, prior_ids, total_bytes = set(), {}, set(), 0
    for split in PRIOR_SPLITS:
        rows = prior_sources_by_split[split]
        _require(type(rows) is list and 1 <= len(rows) <= 4096, "nonempty bounded prior split required")
        ids, texts, templates = set(), set(), Counter()
        for row in rows:
            text, pieces = _source(row)
            _require(row["id"] not in ids, "duplicate prior source identity within split")
            ids.add(row["id"]); prior_ids.add(row["id"])
            texts.update(_normal(item) for item in [text, *pieces])
            templates.update(_old_template(piece) for piece in pieces)
            total_bytes += len(text.encode("utf-8"))
            _require(total_bytes <= 16 * 1024**2, "prior literal blacklist exceeds byte bound")
        forbidden.update(texts)
        blacklists[split] = dict(rows=len(rows), literal_and_clause_unique=len(texts),
                                source_rows_sha256=digest(rows), prior_template_counts=dict(sorted(templates.items())))
    train_ids, train_literals, seen, source_labels = set(), set(), set(), {}
    for row in training_rows:
        text, pieces = _source(row, training=True)
        _require(row["id"] not in train_ids and _normal(text) not in train_literals,
            "duplicate training identity or normalized source")
        train_ids.add(row["id"]); train_literals.add(_normal(text))
        target = row["target"]
        _rules(target, validate_rule); _encode(target, codec)
        _require(len(pieces) == len(target["rules"]), "training source/rule count differs")
        for piece, rule in zip(pieces, target["rules"]):
            _require(_normal(piece) in forbidden, "training clause absent from explicit prior blacklists")
            key = _normal(piece)
            _require(key not in source_labels or source_labels[key] == rule,
                "same training source has conflicting reference labels")
            source_labels[key] = rule
            seen.add((rule["actor"], rule["action"]))
    matchings = _matching_decomposition(seen, 3, seed, "training_seen")
    unseen = {(a, b) for a in ACTORS for b in ACTIONS} - seen
    unseen_matchings = _matching_decomposition(unseen, 2, seed, "training_unseen")
    source_rows, references, family_reports = [], [], []
    used_literals, used_paragraphs = set(), set()
    for family_index, family in enumerate(FAMILIES):
        pairs = [*matchings[family_index], *unseen_matchings[family_index % 2]]
        clauses = []
        for actor, action in pairs:
            for object_ in OBJECTS:
                for modality in MODALITIES:
                    sentence = _sentence(family, actor, action, object_, modality)
                    normalized = _normal(sentence)
                    _require(normalized not in forbidden and normalized not in used_literals,
                        "new literal overlaps prior blacklist or another authored clause")
                    used_literals.add(normalized)
                    rule = dict(actor=actor, action=action, object=object_, modality=modality,
                                conditions=[], exceptions=[], temporal=[])
                    _rules({"rules": [rule]}, validate_rule)
                    clauses.append(dict(source_text=sentence, source_sha256=text_sha(sentence),
                        rule=rule, training_pair_seen=(actor, action) in seen))
        for count, index, members in _compose(clauses, family, seed):
            source = "\n\n".join(item["source_text"] for item in members)
            _require(_normal(source) not in forbidden and _normal(source) not in used_paragraphs,
                "new paragraph overlaps prior blacklist or another paragraph")
            used_paragraphs.add(_normal(source))
            identity = "fresh-authored:" + text_sha(source)
            _require(identity not in prior_ids and identity not in train_ids, "new identity overlaps original identity")
            target = {"rules": [deepcopy(item["rule"]) for item in members]}
            components, offset = [], 0
            for slot, item in enumerate(members):
                end = offset + len(item["source_text"])
                components.append(dict(slot=slot, source_sha256=item["source_sha256"],
                    char_start=offset, char_end=end, byte_start=len(source[:offset].encode()),
                    byte_end=len(source[:end].encode()), training_pair_seen=item["training_pair_seen"]))
                offset = end + 2
            source_rows.append(dict(id=identity, source_text=source))
            references.append(dict(id=identity, source_text=source, source_sha256=text_sha(source),
                split="fresh_authored_holdout", group_id=family, template_family=family,
                clause_count=count, index_within_family_length=index, target=target,
                target_sha256=digest(target), target_ids=_encode(target, codec),
                components=components, codec_sha256=digest(codec),
                reference_origin="authored literal clause ordinal to rule ordinal; review pending", **FALSE))
        family_reports.append(dict(template_family=family, paragraph_count=16, clause_occurrences=60,
            training_seen_pairs=[list(pair) for pair in matchings[family_index]],
            training_unseen_pairs=[list(pair) for pair in unseen_matchings[family_index % 2]],
            training_seen_clause_occurrences=30, training_unseen_clause_occurrences=30,
            actor_counts=dict(Counter(item["rule"]["actor"] for item in clauses)),
            action_counts=dict(Counter(item["rule"]["action"] for item in clauses)),
            object_counts=dict(Counter(item["rule"]["object"] for item in clauses)),
            modality_counts=dict(Counter(item["rule"]["modality"] for item in clauses))))
    _require(len(source_rows) == 48 and len(used_literals) == 180, "fixed holdout inventory differs")
    receipt = dict(schema=SCHEMA, complete=True, seed=seed, split="fresh_authored_holdout",
        sealed_comparison_sha256=sealed_comparison_sha256, comparison_seal_verified=False,
        training_rows_sha256=digest(training_rows), prior_sources_by_split_sha256=digest(prior_sources_by_split),
        prior_split_inventory=blacklists, codec_sha256=digest(codec), full_vocabulary_size=32,
        source_rows_sha256=digest(source_rows), references_sha256=digest(references),
        paragraph_count=48, clause_occurrences=180, unique_clauses=180,
        paragraph_counts_by_length=dict(Counter(str(row["clause_count"]) for row in references)),
        training_seen_pairs=[list(pair) for pair in sorted(seen)],
        training_unseen_pairs=[list(pair) for pair in sorted(unseen)], family_reports=family_reports,
        source_join="two literal newline characters", source_rows_contain_targets=False,
        family_split_policy="all three new syntactic families are postfit-only",
        prior_template_policy="every supplied prior clause matches one of nine exact active v2 templates; unknown templates rejected",
        template_separation_scope="declared authored construction families, not linguistic equivalence proof",
        authored_modal_assumption="passive may be denotes permission; no epistemic reading is represented",
        source_exclusion_policy="casefold whitespace-normalized paragraphs and literal clauses against all four supplied splits",
        target_provenance="authored fixed lexical contract; supplied syntax validator only",
        input_authenticity_scope="caller-authenticated files required; hashes alone do not establish completeness or lifecycle",
        evaluation_policy="compare all sealed arms once after fitting; do not select or update on this cohort",
        expected_unique_encoder_sources=216, encoder_context_tokens=512, decoder_output_tokens=512,
        encoder_token_limit_checked=False, decoder_target_limit_checked=True, **FALSE)
    receipt["receipt_sha256"] = digest(receipt)
    return dict(source_rows=source_rows, references=references, receipt=receipt)


__all__ = ["build_holdout"]
