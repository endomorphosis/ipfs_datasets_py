"""Training-source clause-order diagnostics, never a generation or admit path.

The preparation uses authenticated, already authored components. Only their
order changes; text is not repaired and labels never enter an encoder/model.
All scoring is posthoc. Nonzero source distances do not prove recoverable order.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import re
import statistics

SCHEMA = "training-clause-order-diagnostic/v1"
FIELDS = ("actor", "action", "modality", "object")
RULE_FIELDS = set(FIELDS) | {"conditions", "exceptions", "temporal"}
COUNTS = (1, 2, 4, 8)
FALSE = dict(admitted=False, qualified=False, formalized=False, proof_authority=False,
    source_semantics_verified=False, fresh_holdout=False, lake_executed=False,
    training_executed=False, encoder_executed=False, generation_executed=False,
    native_validation_executed=False, order_recoverability_proven=False)
TOKEN = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
                   r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
                   r'|true|false|null|[{}\[\],:]')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def text_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _codec(codec):
    require(type(codec) is dict and set(codec) == {"schema", "target_vocabulary"}
        and codec["schema"] == "typed-json-lexical/v1", "exact lexical codec required")
    vocabulary = codec["target_vocabulary"]
    require(type(vocabulary) is list and 3 < len(vocabulary) <= 65536
        and all(type(token) is str and token for token in vocabulary)
        and len(set(vocabulary)) == len(vocabulary)
        and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"], "invalid vocabulary")
    return vocabulary


def _encode(target, codec):
    vocabulary = _codec(codec); positions = {word: i for i, word in enumerate(vocabulary)}
    text = raw(target).decode("utf-8"); tokens = TOKEN.findall(text)
    require("".join(tokens) == text and all(token in positions for token in tokens),
        "complete target must use existing codec")
    ids = [1] + [positions[token] for token in tokens] + [2]
    require(len(ids) <= 512 and all(value >= 3 for value in ids[1:-1]),
        "complete target exceeds fixed output limit")
    return ids


def _rule(rule):
    require(type(rule) is dict and set(rule) == RULE_FIELDS
        and all(type(rule[field]) is str and rule[field] for field in FIELDS)
        and rule["modality"] in ("F", "O", "P"), "complete authored rule required")
    for field in ("conditions", "exceptions", "temporal"):
        values = rule[field]
        require(type(values) is list and len(values) <= 4
            and all(type(value) is str and value for value in values)
            and values == sorted(set(values)), "canonical qualifier arrays required")


def _no_authority(row):
    require(all(row.get(key, False) is False for key in FALSE)
        and row.get("truncated", False) is False, "diagnostic authority/truncation required")


def _validate_parent(row, bound, inventory, codec):
    require(type(row) is dict and row.get("split") == "train"
        and row.get("clause_count") in COUNTS and type(row["clause_count"]) is int,
        "only authored training paragraphs permitted")
    _no_authority(row)
    text = row["source_text"]; count = row["clause_count"]
    require(type(text) is str and 0 < len(text) <= 32768 and row["source_sha256"] == text_digest(text)
        and row["source_char_count"] == len(text) and row["source_byte_count"] == len(text.encode("utf-8")),
        "parent source hash/size mismatch")
    target = row["target"]
    require(type(target) is dict and set(target) == {"rules"} and type(target["rules"]) is list
        and len(target["rules"]) == count, "complete parent target required")
    for rule in target["rules"]: _rule(rule)
    require(row["target_sha256"] == digest(target) and row["codec_sha256"] == digest(codec)
        and row["target_ids"] == _encode(target, codec), "parent target/codec mismatch")
    require(type(bound) is dict and bound["id"] == row["id"] and bound["split"] == "train"
        and all(bound[key] == row[key] for key in ("source_text", "source_sha256", "group_id",
            "target_component_ids", "target_ids", "codec_sha256")), "separate curriculum binding mismatch")
    tokens = bound.get("source_tokens")
    require(type(tokens) is dict and tokens.get("source_sha256") == row["source_sha256"]
        and tokens.get("encoder_context_tokens") == 512 and tokens.get("truncated") is False
        and tokens.get("padded") is False and type(tokens.get("token_count")) is int
        and 0 < tokens["token_count"] <= 512 and tokens.get("forward_token_count") == tokens["token_count"]
        and tokens.get("tokenizer_profile_id") == "gte-small:17e1f347d17fe144873b1201da91788898c639cd"
        and tokens.get("tokenizer_sha256") == "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0",
        "original full-source token-count receipt mismatch")
    parts = row["components"]; source_parts = bound["components"]
    require(type(parts) is list and len(parts) == count and type(source_parts) is list
        and len(source_parts) == count, "all component bindings required")
    texts = []; char_start = byte_start = 0; component_ids = []
    for i, (part, source_part, rule) in enumerate(zip(parts, source_parts, target["rules"])):
        require(type(part) is dict and part.get("position") == i and part.get("split") == "train"
            and part["id"] in inventory, "training component identity/position mismatch")
        identity = inventory[part["id"]]
        require(all(part.get(key) == value for key, value in identity.items()),
            "component differs from immutable original inventory")
        cs, ce, bs, be = (part[key] for key in ("char_start", "char_end", "byte_start", "byte_end"))
        require(all(type(value) is int for value in (cs, ce, bs, be)) and cs == char_start
            and bs == byte_start and cs < ce <= len(text) and bs < be <= len(text.encode("utf-8")),
            "component offsets invalid")
        clause = text[cs:ce]
        require(text.encode("utf-8")[bs:be] == clause.encode("utf-8")
            and text_digest(clause) == part["source_sha256"]
            and text_digest(" ".join(clause.casefold().split())) == part["normalized_source_sha256"]
            and digest({"rules": [rule]}) == part["target_sha256"]
            and part["logical_slot"] == [rule[field] for field in ("actor", "action", "object")],
            "component text, rule, or logical slot mismatch")
        require(type(source_part) is dict and all(source_part.get(key) == value for key, value in dict(
            id=part["id"], split="train", group_id=part["group_id"], source_sha256=part["source_sha256"],
            target_sha256=part["target_sha256"], source_text=clause, start_char=cs, end_char=ce).items()),
            "separate component source binding mismatch")
        original = part["original_metadata"]
        require(all(original.get(key) == part[key] for key in ("id", "group_id", "source_sha256", "split")),
            "component original metadata mismatch")
        _no_authority(original)
        texts.append(clause); component_ids.append(part["id"])
        char_start, byte_start = ce + 2, be + 2
    require("\n\n".join(texts) == text and component_ids == row["target_component_ids"]
        and len(set(component_ids)) == count and len({tuple(part["logical_slot"]) for part in parts}) == count,
        "exact ordered independent component composition required")
    groups = sorted({part["group_id"] for part in parts})
    require(row["component_group_ids"] == groups
        and row["group_id"] == "authored-component-groups:" + digest(groups), "component group binding differs")
    return texts


def build_order_variants(paragraphs, curriculum_inputs, *, codec):
    """Return108 unique training rows and120 request records, no model execution.

    First48 rows retain original training IDs/order. The12 two-clause rotations
    alias their reversals; they are not independent rows or extra observations.
    The caller must bind the original input file hashes before invoking this API.
    """
    _codec(codec)
    require(type(paragraphs) is dict and paragraphs.get("schema") == "authored-legal-paragraph-curriculum/v1"
        and paragraphs.get("codec") == codec and paragraphs.get("codec_sha256") == digest(codec),
        "exact authored paragraph preparation required")
    _no_authority(paragraphs)
    train, validation = paragraphs["train"], paragraphs["validation"]
    require(type(train) is list and type(validation) is list and len(train) == len(validation) == 48,
        "complete fixed48/48 original splits required")
    require(Counter(row["clause_count"] for row in train) == {count: 12 for count in COUNTS},
        "fixed12 training rows per clause count required")
    require(type(curriculum_inputs) is list and len(curriculum_inputs) == 96
        and len({row["id"] for row in curriculum_inputs}) == 96, "exact separate curriculum inventory required")
    bindings = {row["id"]: row for row in curriculum_inputs}
    require(set(bindings) == {row["id"] for row in train + validation}, "curriculum row inventory differs")
    inventories = paragraphs["original_split_inventory"]
    inventory = {row["id"]: row for row in inventories["train"]}
    require(len(inventory) == len(inventories["train"]) and inventory, "unique original training inventory required")
    for field in ("id", "group_id", "source_sha256", "normalized_source_sha256"):
        require(not {row[field] for row in inventories["train"]} & {row[field] for row in inventories["validation"]},
            "original train/validation overlap: " + field)
    require(all(row.get("split") == "validation" for row in validation)
        and not {row["id"] for row in train} & {row["id"] for row in validation}
        and not {row["source_sha256"] for row in train} & {row["source_sha256"] for row in validation},
        "paragraph train/validation overlap")
    texts = {row["id"]: _validate_parent(row, bindings[row["id"]], inventory, codec) for row in train}
    require(len(texts) == 48 and len({row["source_sha256"] for row in train}) == 48,
        "unique original training paragraphs required")
    rows, requests, aliases, pairs = [], [], [], []
    seen = {}

    def add(parent, variant, permutation):
        count = parent["clause_count"]; inverse = [permutation.index(i) for i in range(count)]
        selected_text = [texts[parent["id"]][i] for i in permutation]
        source = "\n\n".join(selected_text); source_sha = text_digest(source)
        target = {"rules": [deepcopy(parent["target"]["rules"][i]) for i in permutation]}
        request_id = parent["id"] + ":order:" + variant
        bag = digest(sorted((part["id"], part["source_sha256"], part["target_sha256"]) for part in parent["components"]))
        request = dict(request_id=request_id, parent_id=parent["id"], variant=variant,
            permutation=permutation, inverse_permutation=inverse, clause_count=count,
            source_sha256=source_sha, target_sha256=digest(target), clause_bag_sha256=bag)
        if source_sha in seen:
            previous = seen[source_sha]
            require(previous["parent_id"] == parent["id"] and previous["target_sha256"] == digest(target)
                and count == 2 and variant == "rotate_left_one" and previous["variant"] == "reverse",
                "unexpected duplicate source; do not count it as independent evidence")
            alias = dict(request, id=previous["id"], alias_of_request=previous["request_id"],
                independent_observation=False)
            aliases.append(alias); requests.append(alias); return
        row = deepcopy(parent)
        row_id = parent["id"] if variant == "original" else "order-diagnostic:train:" + source_sha
        components = []; char_start = byte_start = 0
        for position, index in enumerate(permutation):
            component = deepcopy(parent["components"][index]); clause = texts[parent["id"]][index]
            component.update(position=position, char_start=char_start, char_end=char_start + len(clause),
                byte_start=byte_start, byte_end=byte_start + len(clause.encode("utf-8")))
            char_start, byte_start = component["char_end"] + 2, component["byte_end"] + 2
            components.append(component)
        row.update(id=row_id, source_text=source, source_sha256=source_sha,
            source_char_count=len(source), source_byte_count=len(source.encode("utf-8")),
            target=target, target_sha256=digest(target), target_ids=_encode(target, codec),
            target_component_ids=[component["id"] for component in components], components=components,
            source_encoder_token_count=None, source_encoder_token_limit_checked=False,
            order_diagnostic=dict(request), **FALSE)
        # A new source must never carry an old numeric cache or token receipt.
        for key in ("embedding", "embedding_result", "embedding_sha256", "source_tokens"):
            row.pop(key, None)
        request = dict(request, id=row_id, alias_of_request=None, independent_observation=True)
        rows.append(row); requests.append(request); seen[source_sha] = request
        if variant != "original": pairs.append(dict(request))

    for parent in train: add(parent, "original", list(range(parent["clause_count"])))
    for parent in train:
        count = parent["clause_count"]
        if count > 1:
            add(parent, "reverse", list(reversed(range(count))))
            add(parent, "rotate_left_one", list(range(1, count)) + [0])
    require(len(rows) == 108 and len(requests) == 120 and len(aliases) == 12 and len(pairs) == 60,
        "fixed original/permutation/alias counts differ")
    require(not {row["source_sha256"] for row in rows} & {row["source_sha256"] for row in validation},
        "permuted training source overlaps validation")
    result = dict(schema=SCHEMA, rows=rows, requests=requests, aliases=aliases, pairs=pairs,
        original_ids=[row["id"] for row in train], original_count=48, unique_source_count=108,
        requested_variant_count=120, duplicate_alias_count=12, changed_source_count=60,
        codec_sha256=digest(codec), paragraph_input_sha256=digest(paragraphs),
        curriculum_inputs_sha256=digest(curriculum_inputs), validation_unchanged_sha256=digest(validation),
        training_only=True, source_join="two literal newline characters", encoder_context_tokens=512,
        output_limit=512, generation_temperature=0, **FALSE)
    result["preparation_sha256"] = digest(result)
    return result


def _prepared(preparation):
    require(type(preparation) is dict and preparation.get("schema") == SCHEMA
        and preparation.get("preparation_sha256") == digest({k: v for k, v in preparation.items() if k != "preparation_sha256"}),
        "sealed preparation required")
    require(len(preparation["rows"]) == 108 and len(preparation["original_ids"]) == 48
        and len(preparation["pairs"]) == 60 and len(preparation["aliases"]) == 12,
        "fixed preparation inventory required")
    return {row["id"]: row for row in preparation["rows"]}


def _vector(value):
    require(type(value) is list and 1 <= len(value) <= 4096
        and all(type(x) in (float, int) and math.isfinite(x) and abs(x) <= 1e100 for x in value),
        "bounded finite vector required")
    return value


def vector_distance(left, right):
    """Raw and normalized distances; zero-vector cosine is explicitly absent."""
    _vector(left); _vector(right); require(len(left) == len(right), "vector dimensions differ")
    a = math.sqrt(math.fsum(x*x for x in left)); b = math.sqrt(math.fsum(x*x for x in right))
    delta = [x-y for x, y in zip(left, right)]
    cosine = max(-1., min(1., math.fsum((x/a)*(y/b) for x, y in zip(left, right)))) if a and b else None
    return dict(l2=math.sqrt(math.fsum(x*x for x in delta)), max_abs_delta=max(map(abs, delta)),
        mean_abs_delta=math.fsum(map(abs, delta))/len(delta), left_norm=a, right_norm=b,
        cosine_distance=None if cosine is None else 1.-cosine,
        normalized_l2=None if cosine is None else math.sqrt(math.fsum((x/a-y/b)**2 for x, y in zip(left, right))),
        zero_norm_present=not bool(a and b), exact_values_equal=left == right)


def _summarize_distances(rows):
    result = dict(count=len(rows), exactly_equal=sum(row["exact_values_equal"] for row in rows))
    for key in ("l2", "max_abs_delta", "mean_abs_delta", "cosine_distance", "normalized_l2"):
        values = [row[key] for row in rows if row[key] is not None]
        result[key] = dict(count=len(values), minimum=min(values) if values else None,
            maximum=max(values) if values else None, mean=statistics.fmean(values) if values else None,
            median=statistics.median(values) if values else None)
    return result


def paired_vector_metrics(preparation, vectors_by_id, *, space, repeat_vectors_by_id=None):
    """Compare60 unique changes,48 cyclic different-parent anchors and48 repeats.

    Baseline uses the next original within its length, skipping the same clause
    bag. Ratios have no acceptance threshold and do not demonstrate decoding.
    Raw vectors remain the caller's retained, provenance-bound observations.
    """
    rows = _prepared(preparation)
    require(type(space) is str and space and type(vectors_by_id) is dict and set(vectors_by_id) == set(rows),
        "exact source-only vector inventory required")
    dimensions = {len(_vector(vector)) for vector in vectors_by_id.values()}
    require(len(dimensions) == 1, "one vector geometry required")
    original_ids = preparation["original_ids"]
    pairs = [dict(id=pair["id"], parent_id=pair["parent_id"], clause_count=pair["clause_count"],
        variant=pair["variant"], distance=vector_distance(vectors_by_id[pair["parent_id"]], vectors_by_id[pair["id"]]))
        for pair in preparation["pairs"]]
    baselines = []; repeats = []
    for count in COUNTS:
        group = [key for key in original_ids if rows[key]["clause_count"] == count]
        for i, key in enumerate(group):
            other = next((group[(i+j) % len(group)] for j in range(1, len(group))
                if rows[group[(i+j) % len(group)]]["order_diagnostic"]["clause_bag_sha256"]
                != rows[key]["order_diagnostic"]["clause_bag_sha256"]), None)
            require(other is not None, "different-parent different-bag baseline unavailable")
            baselines.append(dict(id=key, other_id=other, clause_count=count,
                distance=vector_distance(vectors_by_id[key], vectors_by_id[other])))
    if repeat_vectors_by_id is not None:
        require(type(repeat_vectors_by_id) is dict and set(repeat_vectors_by_id) == set(original_ids),
            "exact48 repeated original vectors required")
        repeats = [dict(id=key, clause_count=rows[key]["clause_count"],
            distance=vector_distance(vectors_by_id[key], repeat_vectors_by_id[key])) for key in original_ids]
    by_length = {}
    for count in COUNTS:
        changed = _summarize_distances([pair["distance"] for pair in pairs if pair["clause_count"] == count])
        baseline = _summarize_distances([pair["distance"] for pair in baselines if pair["clause_count"] == count])
        noise = _summarize_distances([pair["distance"] for pair in repeats if pair["clause_count"] == count])
        ratios = {}
        for name, denominator in (("different_parent", baseline), ("same_text_repeat", noise)):
            ratios[name] = {key: changed[key]["mean"]/denominator[key]["mean"]
                if changed[key]["mean"] is not None and denominator[key]["mean"] not in (None, 0.) else None
                for key in ("l2", "normalized_l2", "cosine_distance")}
        by_length[str(count)] = dict(order_change=changed, different_parent=baseline, same_text_repeat=noise,
            mean_distance_ratios=ratios)
    return dict(schema="training-clause-order-vector-metrics/v1", preparation_sha256=preparation["preparation_sha256"],
        space=space, dimension=next(iter(dimensions)), pairs=pairs, different_parent_pairs=baselines,
        repeat_pairs=repeats, by_length=by_length, no_acceptance_threshold=True,
        ratio_zero_denominator_policy="null; inspect absolute distances", **FALSE)


def _observed_score(row, rules):
    expected = row["target"]["rules"]
    facets = {field: sum(i < len(rules) and type(rules[i]) is dict and rules[i].get(field) == rule[field]
        for i, rule in enumerate(expected)) for field in FIELDS}
    return dict(expected_rules=len(expected), generated_rules=len(rules), scalar_correct=facets,
        actor_action_pairs_correct=sum(i < len(rules) and type(rules[i]) is dict
            and all(rules[i].get(field) == rule[field] for field in ("actor", "action")) for i, rule in enumerate(expected)),
        ordered_rules_correct=sum(i < len(rules) and rules[i] == rule for i, rule in enumerate(expected)),
        ordered_document_exact=rules == expected)


def _equivariance(original_row, changed_row, original, changed, permutation):
    """Report both all slots and reference-changing slots, posthoc only."""
    result = {}
    for label, fields in [(field, (field,)) for field in FIELDS] + [("actor_action", ("actor", "action"))]:
        counts = dict(slots=0, informative_slots=0, comparable_slots=0,
            matches_fixed=0, matches_permuted=0, informative_comparable_slots=0,
            informative_matches_fixed=0, informative_matches_permuted=0)
        for slot, previous in enumerate(permutation):
            counts["slots"] += 1
            informative = any(original_row["target"]["rules"][slot][field]
                != changed_row["target"]["rules"][slot][field] for field in fields)
            counts["informative_slots"] += informative
            def values(rules, index):
                if index >= len(rules) or type(rules[index]) is not dict: return None
                value = tuple(rules[index].get(field) for field in fields)
                return value if all(type(item) is str for item in value) else None
            actual, fixed, moved = values(changed, slot), values(original, slot), values(original, previous)
            if any(value is None for value in (actual, fixed, moved)): continue
            counts["comparable_slots"] += 1
            counts["matches_fixed"] += actual == fixed
            counts["matches_permuted"] += actual == moved
            if informative:
                counts["informative_comparable_slots"] += 1
                counts["informative_matches_fixed"] += actual == fixed
                counts["informative_matches_permuted"] += actual == moved
        result[label] = counts
    return result


def _decode_prediction(prediction, codec):
    require(type(prediction) is dict and type(prediction.get("token_ids")) is list
        and len(prediction["token_ids"]) <= 512 and type(prediction.get("eos_reached")) is bool,
        "bounded actual prediction and EOS observation required")
    ids = prediction["token_ids"]; vocabulary = codec["target_vocabulary"]
    require(all(type(token) is int and 0 <= token < len(vocabulary) for token in ids), "invalid output token ID")
    if any(token < 3 for token in ids): return [], False
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise ValueError("duplicate key")
            value[key] = item
        return value
    try:
        value = json.loads("".join(vocabulary[token] for token in ids), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        if type(value) is not dict or set(value) != {"rules"} or type(value["rules"]) is not list or len(value["rules"]) > 32:
            return [], False
        for rule in value["rules"]: _rule(rule)
        return value["rules"], True
    except (ValueError, TypeError, RecursionError):
        return [], False


def paired_prediction_metrics(preparation, predictions_by_id, *, codec):
    """Posthoc generated rules, never an alternative qualification gate."""
    rows = _prepared(preparation); _codec(codec)
    require(digest(codec) == preparation["codec_sha256"] and type(predictions_by_id) is dict
        and set(predictions_by_id) == set(rows), "exact actual prediction inventory/codec required")
    decoded = {}; scores = []
    for key, row in rows.items():
        prediction = predictions_by_id[key]
        require(prediction.get("id") == key, "prediction identity differs")
        rules, valid = _decode_prediction(prediction, codec); decoded[key] = rules
        scores.append(dict(id=key, clause_count=row["clause_count"], variant=row["order_diagnostic"]["variant"],
            syntax_valid=valid, eos_reached=prediction["eos_reached"],
            exact_target_with_eos=valid and prediction["eos_reached"] and rules == row["target"]["rules"],
            **_observed_score(row, rules)))
    pairs = []
    for pair in preparation["pairs"]:
        original = decoded[pair["parent_id"]]; changed = decoded[pair["id"]]
        can_permute = len(original) == pair["clause_count"]
        permutation = [original[i] for i in pair["permutation"]] if can_permute else None
        pairs.append(dict(id=pair["id"], parent_id=pair["parent_id"], clause_count=pair["clause_count"],
            same_generated_tokens=predictions_by_id[pair["id"]]["token_ids"] == predictions_by_id[pair["parent_id"]]["token_ids"],
            original_prediction_has_expected_count=can_permute,
            matches_permuted_original_prediction=can_permute and changed == permutation,
            matches_fixed_original_prediction=bool(original) and changed == original,
            equivariance=_equivariance(rows[pair["parent_id"]], rows[pair["id"]], original, changed, pair["permutation"])))
    return dict(schema="training-clause-order-prediction-metrics/v1", preparation_sha256=preparation["preparation_sha256"],
        rows=scores, pairs=pairs, scoring_only_target_access=True, **FALSE)


def paired_scalar_metrics(preparation, logits_by_id, *, codec):
    """Raw source readout argmax diagnostics; potential slots are not visits."""
    rows = _prepared(preparation); vocabulary = _codec(codec)
    require(digest(codec) == preparation["codec_sha256"] and type(logits_by_id) is dict
        and set(logits_by_id) == set(rows), "exact raw scalar inventory/codec required")
    argmax = {}; decoded = {}; scores = []
    for key, row in rows.items():
        logits = logits_by_id[key]
        require(type(logits) is list and len(logits) == 8 and all(type(slot) is list and len(slot) == 4 for slot in logits),
            "eight source slots and four fields required")
        ids = []
        for slot in logits:
            require(all(len(_vector(field)) == len(vocabulary) for field in slot), "full vocabulary source scores required")
            ids.append([max(range(len(field)), key=field.__getitem__) for field in slot])
        values = []
        for slot in ids:
            rule = {}
            for field, token in zip(FIELDS, slot):
                try: value = json.loads(vocabulary[token]) if token >= 3 else None
                except ValueError: value = None
                rule[field] = value if type(value) is str else None
            values.append(rule)
        argmax[key] = ids; decoded[key] = values
        score = _observed_score(row, values[:row["clause_count"]])
        score.pop("ordered_document_exact"); score.pop("ordered_rules_correct")
        scores.append(dict(id=key, clause_count=row["clause_count"], predicted_token_ids=ids, **score))
    pairs = []
    for pair in preparation["pairs"]:
        original = argmax[pair["parent_id"]]; actual = argmax[pair["id"]]; count = pair["clause_count"]
        moved = [original[i] for i in pair["permutation"]]
        def flatten(value): return [number for slot in value for field in slot for number in field]
        previous_logits = logits_by_id[pair["parent_id"]]
        actual_logits = flatten(logits_by_id[pair["id"]][:count])
        fixed_distance = vector_distance(actual_logits, flatten(previous_logits[:count]))
        moved_distance = vector_distance(actual_logits, flatten([previous_logits[i] for i in pair["permutation"]]))
        pairs.append(dict(id=pair["id"], parent_id=pair["parent_id"], clause_count=count,
            scalar_slots_scored=count*4,
            matches_permuted_original=sum(a == b for left, right in zip(actual[:count], moved) for a, b in zip(left, right)),
            matches_fixed_original=sum(a == b for left, right in zip(actual[:count], original[:count]) for a, b in zip(left, right)),
            ordered_argmax_equivariant=actual[:count] == moved,
            full_logit_fixed_slot_distance=fixed_distance, full_logit_permuted_slot_distance=moved_distance,
            equivariance=_equivariance(rows[pair["parent_id"]], rows[pair["id"]],
                decoded[pair["parent_id"]], decoded[pair["id"]], pair["permutation"])))
    return dict(schema="training-clause-order-scalar-metrics/v1", preparation_sha256=preparation["preparation_sha256"],
        rows=scores, pairs=pairs, scoring_only_target_access=True, potential_slot_scores_not_generation_visits=True,
        argmax_tie_policy="lowest vocabulary ID; ties are not evidence of preference", **FALSE)
