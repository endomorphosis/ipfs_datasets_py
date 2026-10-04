"""Closed, training-only replacement of parent rows by authenticated permutations.

This module neither loads models nor runs inference. The unchanged training
objective may consume the selected full source/target row; generation never sees
these labels. Normalization, curriculum and count sampling remain parent-owned.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import math
import struct

from . import order_source_diagnostic as order

SCHEMA = "training-order-augmentation-selector/v1"
FALSE = dict(order.FALSE, checkpoint_promoted=False, selection_changed=False)
require, digest, text_digest = order.require, order.digest, order.text_digest


def _native_vector(vector):
    require(type(vector) is list and len(vector) == 384
        and all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 1 for x in vector),
        "finite384-dimensional native source vector required")
    require(all(struct.unpack("f", struct.pack("f", float(x)))[0] == x for x in vector),
        "actual float32 source vector values required; no implicit conversion")
    require(abs(math.fsum(x*x for x in vector)-1.) <= 1e-4,
        "verified normalized local encoder vector required")


def _rows(rows, split):
    require(type(rows) is list and len(rows) == 48, "complete original48 " + split + " rows required")
    for row in rows:
        require(type(row) is dict and {"id", "source_text", "input", "target_ids"} == set(row)
            and type(row["id"]) is str and 0 < len(row["id"]) <= 512
            and type(row["source_text"]) is str and 0 < len(row["source_text"]) <= 32768,
            "bounded original source row required")
        order._no_authority(row); _native_vector(row["input"])
        require(type(row["target_ids"]) is list and 4 <= len(row["target_ids"]) <= 512
            and all(type(token) is int for token in row["target_ids"])
            and row["target_ids"][0] == 1 and row["target_ids"][-1] == 2
            and all(token >= 3 for token in row["target_ids"][1:-1]),
            "complete bounded original target IDs required")
    require(len({row["id"] for row in rows}) == len({text_digest(row["source_text"]) for row in rows}) == 48,
        "unique original source IDs/text required")
    require(len({" ".join(row["source_text"].casefold().split()) for row in rows}) == 48,
        "duplicate normalized source in original split")


def _tokens(value):
    require(type(value) is dict and set(value) == {"input_ids", "attention_mask", "token_type_ids"},
        "actual full-forward token capture required")
    ids, masks, types = (value[k] for k in ("input_ids", "attention_mask", "token_type_ids"))
    require(type(ids) is list and 2 <= len(ids) <= 512
        and all(type(i) is int and 0 <= i < 30522 for i in ids)
        and ids[0] == 101 and ids[-1] == 102
        and type(masks) is list and masks == [1]*len(ids)
        and (types is None or type(types) is list and len(types) == len(ids)
             and all(type(i) is int and i == 0 for i in types)),
        "complete untruncated gte-small token capture required")
    return ids


class _OrderSelector:
    """Fresh per-fit selector. Counts are draws, not committed optimizer updates."""
    def __init__(self, parents, effective_rows, effective_references, variants, receipt):
        self._parents = deepcopy(parents)
        self._rows = deepcopy(effective_rows)
        self._references = deepcopy(effective_references)
        self._variants = deepcopy(variants)
        self._receipt = deepcopy(receipt)
        self._parent_by_id = {row["id"]: row for row in self._parents}
        self._effective_by_id = {row["id"]: row for row in self._rows}
        self._occurrences = {row["id"]: 0 for row in self._parents}
        self._variant_draws = {row["id"]: 0 for row in self._rows}
        self._batches = 0
        self._sequence = hashlib.sha256()

    @property
    def effective_rows(self):
        return deepcopy(self._rows)

    @property
    def effective_references(self):
        return deepcopy(self._references)

    def select(self, parent_batch):
        """Cycle each parent's unique original/reverse/rotate rows without RNG.

        A draw can precede a deadline stop. The trainer must retain committed
        parent/effective IDs separately instead of treating this as exposure.
        Validation of the entire request precedes any counter mutation.
        """
        require(type(parent_batch) is list and 1 <= len(parent_batch) <= 128
            and all(type(row) is dict and row.get("id") in self._parent_by_id for row in parent_batch)
            and len({row["id"] for row in parent_batch}) == len(parent_batch),
            "unique original parent batch required")
        require(all(row == self._parent_by_id[row["id"]] for row in parent_batch),
            "selector parent rows changed")
        result = []
        for parent in parent_batch:
            key = parent["id"]; candidates = self._variants[key]
            selected = candidates[self._occurrences[key] % len(candidates)]
            result.append(deepcopy(self._effective_by_id[selected]))
        # Assertions do not repair or truncate targets and do not change batch size.
        require(len(result) == len(parent_batch) and all(len(a["target_ids"]) == len(b["target_ids"])
            for a, b in zip(parent_batch, result)), "same-sized full target replacement required")
        for parent, selected in zip(parent_batch, result):
            self._occurrences[parent["id"]] += 1
            self._variant_draws[selected["id"]] += 1
        self._batches += 1
        self._sequence.update(order.raw(dict(parent_ids=[r["id"] for r in parent_batch],
            effective_ids=[r["id"] for r in result])))
        return result

    def snapshot(self):
        return dict(self._receipt, parent_occurrence_counts=dict(self._occurrences),
            variant_draw_counts=dict(self._variant_draws), draw_batches=self._batches,
            draw_rows=sum(self._occurrences.values()), selection_sequence_sha256=self._sequence.hexdigest(),
            draw_counts_are_not_committed_optimizer_exposure=True,
            draws_may_include_uncommitted_final_batch=True,
            variant_ids_by_parent=deepcopy(self._variants))


def prepare(training_rows, validation_rows, *, training_references, preparation,
            embedding_observations, codec):
    """Validate all108 sources, return fresh substitution selector and label rows.

    The enclosing frozen runner must authenticate the previously published
    preparation/embedding file SHA-256 values. This function checks their semantic
    composition, cohort alignment, exact vectors, and fixed token/count budgets.
    It leaves original training48 available for all existing statistics/gates.
    """
    order._codec(codec); _rows(training_rows, "training"); _rows(validation_rows, "validation")
    train_ids = [row["id"] for row in training_rows]
    validation_ids = {row["id"] for row in validation_rows}
    validation_sources = {text_digest(row["source_text"]) for row in validation_rows}
    normalized = lambda text: text_digest(" ".join(text.casefold().split()))
    validation_normalized_sources = {normalized(row["source_text"]) for row in validation_rows}
    require(not set(train_ids) & validation_ids
        and not {text_digest(row["source_text"]) for row in training_rows} & validation_sources,
        "original training/validation overlap")
    prepared_rows = order._prepared(preparation)
    require(preparation["codec_sha256"] == digest(codec) and preparation["original_ids"] == train_ids
        and [row["id"] for row in preparation["rows"][:48]] == train_ids
        and preparation["training_only"] is True and preparation["encoder_context_tokens"] == 512
        and preparation["output_limit"] == 512 and preparation["generation_temperature"] == 0,
        "sealed original-first training-only preparation required")
    order._no_authority(preparation)
    require(type(training_references) is list and [ref["id"] for ref in training_references] == train_ids,
        "complete aligned original training references required")
    refs = {ref["id"]: ref for ref in training_references}
    for row in training_rows:
        reference = refs[row["id"]]; prepared = prepared_rows[row["id"]]
        require(reference["source_text"] == prepared["source_text"] == row["source_text"]
            and reference["source_sha256"] == prepared["source_sha256"] == text_digest(row["source_text"])
            and reference["target"] == prepared["target"]
            and reference["clause_count"] == prepared["clause_count"]
            and row["target_ids"] == prepared["target_ids"] == order._encode(reference["target"], codec),
            "actual original training source/reference differs")
        order._no_authority(reference)
    require(type(embedding_observations) is dict
        and embedding_observations.get("schema") == "order-source-embedding-observations/v1"
        and embedding_observations.get("observations_count") == 204,
        "complete previously executed local embedding observations required")
    producer = embedding_observations["producer"]
    require(all(producer.get(k) == v for k, v in dict(model_id="thenlper/gte-small",
        revision="17e1f347d17fe144873b1201da91788898c639cd", dimension=384,
        encoder_context_tokens=512, normalized=True, dtype="float32", device="cpu", cpu_threads=1,
        downloads_performed=False, actual_forward_tokens_checked=True, encoder_context_changed=False).items()),
        "unchanged verified local gte-small producer required")
    observations = embedding_observations["observations"]
    require(type(observations) is dict and set(observations) == {"main", "repeat_batch8", "repeat_batch4"},
        "exact executed embedding panels required")
    require(embedding_observations.get("vectors_sha256") == {key: digest(value) for key, value in observations.items()},
        "recorded native observation hashes differ")
    native = {}; token_ids = {}
    for label, count in (("main", 108), ("repeat_batch8", 48), ("repeat_batch4", 48)):
        panel = observations[label]
        expected_ids = list(prepared_rows) if label == "main" else train_ids
        require(type(panel) is list and len(panel) == count
            and [row["input_id"] for row in panel] == expected_ids,
            "exact native observation row identity/order required")
        for row in panel:
            require(row["status"] == "embedded", "untruncated actual embedding required")
            _native_vector(row["vector"]); tokens = _tokens(row["tokens"])
            if label == "main": native[row["input_id"]] = row["vector"]; token_ids[row["input_id"]] = tokens
    for row in training_rows:
        require(native[row["id"]] == row["input"], "original cached input differs from actual re-encoding")

    variants = {key: [] for key in train_ids}; effective_rows = []; effective_refs = []
    by_train = {row["id"]: row for row in training_rows}
    unique_sources = set(); unique_normalized_sources = set()
    reconstructed_requests = []; requests_by_name = {}
    for row in preparation["rows"]:
        order._no_authority(row)
        require(row.get("split") == "train" and row["id"] not in validation_ids
            and row["source_sha256"] not in validation_sources and row["source_sha256"] not in unique_sources,
            "augmented source/ID leakage or duplicate")
        normalized_source = normalized(row["source_text"])
        require(normalized_source not in validation_normalized_sources
            and normalized_source not in unique_normalized_sources,
            "augmented normalized source leakage or duplicate")
        unique_sources.add(row["source_sha256"])
        unique_normalized_sources.add(normalized_source)
        meta = row["order_diagnostic"]; parent_id = meta["parent_id"]
        require(parent_id in by_train and meta["variant"] in ("original", "reverse", "rotate_left_one"),
            "known immutable parent and predeclared variant required")
        parent = prepared_rows[parent_id]; count = parent["clause_count"]
        name = meta["variant"]
        expected_permutation = (list(range(count)) if name == "original" else
            list(reversed(range(count))) if name == "reverse" else list(range(1, count)) + [0])
        require(meta["permutation"] == expected_permutation
            and meta["inverse_permutation"] == [expected_permutation.index(i) for i in range(count)]
            and meta["clause_count"] == row["clause_count"] == count,
            "actual declared clause permutation differs")
        require((name == "original") == (row["id"] == parent_id), "original identity differs")
        texts = []; components = []; cs = bs = 0
        for position, index in enumerate(expected_permutation):
            part = parent["components"][index]
            clause = parent["source_text"][part["char_start"]:part["char_end"]]
            require(parent["source_text"].encode()[part["byte_start"]:part["byte_end"]] == clause.encode()
                and text_digest(clause) == part["source_sha256"]
                and digest({"rules": [parent["target"]["rules"][index]]}) == part["target_sha256"],
                "immutable parent component source/reference changed")
            component = deepcopy(part)
            component.update(position=position, char_start=cs, char_end=cs+len(clause),
                byte_start=bs, byte_end=bs+len(clause.encode()))
            components.append(component); texts.append(clause)
            cs, bs = component["char_end"]+2, component["byte_end"]+2
        text = "\n\n".join(texts)
        target = {"rules": [deepcopy(parent["target"]["rules"][i]) for i in expected_permutation]}
        require(row["source_text"] == text and row["source_sha256"] == text_digest(text)
            and row["target"] == target and row["target_sha256"] == digest(target)
            and row["target_ids"] == order._encode(target, codec)
            and row["components"] == components
            and row["target_component_ids"] == [part["id"] for part in components]
            and meta["clause_bag_sha256"] == parent["order_diagnostic"]["clause_bag_sha256"],
            "variant changed complete clause text/reference/offsets")
        require(len(row["target_ids"]) == len(by_train[parent_id]["target_ids"])
            and len(token_ids[row["id"]]) == len(token_ids[parent_id])
            and Counter(token_ids[row["id"]]) == Counter(token_ids[parent_id]),
            "augmentation must preserve full encoder/output token budgets and token bag")
        require(name == "original" or count > 1, "single-clause augmentation is forbidden")
        variants[parent_id].append(row["id"])
        if name == "original":
            effective_rows.append(deepcopy(by_train[parent_id])); effective_refs.append(deepcopy(refs[parent_id]))
        else:
            effective_rows.append(dict(id=row["id"], source_text=text, input=deepcopy(native[row["id"]]),
                target_ids=deepcopy(row["target_ids"])))
            effective_refs.append(dict(id=row["id"], source_text=text, source_sha256=text_digest(text),
                target=target, clause_count=count))
        request = dict(meta, id=row["id"], alias_of_request=None, independent_observation=True)
        reconstructed_requests.append(request); requests_by_name[parent_id, name] = request
    # The preparation request sequence records the two-clause rotate aliases.
    expected_requests = list(reconstructed_requests[:48]); expected_aliases = []; expected_pairs = []
    for key in train_ids:
        count = prepared_rows[key]["clause_count"]
        expected_names = ["original"] + (["reverse"] if count == 2 else ["reverse", "rotate_left_one"] if count > 2 else [])
        require([prepared_rows[value]["order_diagnostic"]["variant"] for value in variants[key]] == expected_names,
            "unique original-first per-parent cycle differs")
        if count == 1: continue
        reverse = requests_by_name[key, "reverse"]
        expected_requests.append(reverse); expected_pairs.append(reverse)
        if count == 2:
            alias = {**reverse, "request_id": key+":order:rotate_left_one", "variant": "rotate_left_one",
                "alias_of_request": reverse["request_id"], "independent_observation": False}
            expected_requests.append(alias); expected_aliases.append(alias)
        else:
            rotate = requests_by_name[key, "rotate_left_one"]
            expected_requests.append(rotate); expected_pairs.append(rotate)
    require(preparation["requests"] == expected_requests and preparation["aliases"] == expected_aliases
        and preparation["pairs"] == expected_pairs and len(effective_rows) == 108,
        "complete canonical requests/aliases/pairs required; aliases are not training rows")
    receipt = dict(schema=SCHEMA, training_rows_sha256=digest(training_rows),
        training_references_sha256=digest(training_references), validation_rows_sha256=digest(validation_rows),
        effective_rows_sha256=digest(effective_rows), effective_references_sha256=digest(effective_refs),
        preparation_sha256=preparation["preparation_sha256"], embedding_observations_sha256=digest(embedding_observations),
        codec_sha256=digest(codec), original_training_rows=48, effective_rows=108, aliases_excluded=12,
        selection_policy="per_parent_occurrence_original_then_reverse_then_rotate_left_one_unique_cycle",
        normalization_fit_rows="unchanged original48", count_sampler_rows="unchanged original48",
        curriculum_rows="unchanged original48", parent_batch_size_preserved=True,
        source_token_counts_preserved=True, target_token_counts_preserved=True, clause_counts_preserved=True,
        selection_uses_rng=False, target_use="training loss only; never a generation input",
        file_authentication_scope="caller binds exact published preparation/embedding file hashes", **FALSE)
    return _OrderSelector(training_rows, effective_rows, effective_refs, variants, receipt)
