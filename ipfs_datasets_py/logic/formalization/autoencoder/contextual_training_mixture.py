"""Explicit TRAIN paraphrase substitution with original preprocessing ownership.

Pure source/reference validation and sampling; no model forward or optimizer.
The caller authenticates artifact file hashes and freezes the producer closure.
Internal digests bind contents, not their provenance. Missing evaluation vectors
remain explicit; complete source-text exclusion is not semantic independence.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import math
import time

from . import authored_training_paraphrases as authored
from . import clause_source_context as context
from . import decoder_distillation_experiment as core
from . import source_value_decoder_experiment as values
from . import training_paraphrase_source_inputs as producer

SCHEMA = "contextual-training-mixture/v1"
POLICIES = ("original_only", "half_paraphrases")
EVALUATION_DATASETS = ("paragraph_validation", "raw_validation", "raw_test", "raw_canary",
    "exposed_r6", "exposed_r8", "exposed_v3")
PRIOR_DATASETS = set(EVALUATION_DATASETS) | {"paragraph_train", "raw_train", "original_train_bank"}
KEYS = {"policy", "training_bank", "prior_sources_by_dataset", "corpus", "source_plan",
    "source_inputs", "production_report", "evaluation_vectors_by_dataset", "payload_sha256"}
require, digest = core._require, core.digest


def _deadline(deadline):
    require(type(deadline) in (int, float) and math.isfinite(deadline), "finite mixture deadline required")
    if time.monotonic() >= deadline:
        raise TimeoutError("contextual TRAIN mixture deadline")


def _texts(rows):
    result = set()
    for row in rows:
        text, pieces = authored.base._source({k: row[k] for k in ("id", "source_text")})
        result.add(authored.base._normal(text))
        result.update(authored.base._normal(piece) for piece in pieces)
    return result


def _source_rows(rows):
    return [{k: row[k] for k in ("id", "source_text")} for row in rows]


def prepare(training_rows, validation_rows, *, training_references, validation_references,
            source_contexts, codec, validate_rule, mixture, deadline):
    """Authenticate original plus TRAIN-derived sources without fitting statistics.

    The envelope includes all seven prior evaluation source inventories. Native
    vector coverage can be partial, and its exact observed coverage is reported.
    Neither evaluation target labels nor model scores construct any new label.
    """
    _deadline(deadline)
    require(type(mixture) is dict and set(mixture) == KEYS
        and mixture["policy"] in POLICIES
        and mixture["payload_sha256"] == digest({k: v for k, v in mixture.items() if k != "payload_sha256"}),
        "closed authenticated mixture envelope required")
    prior = mixture["prior_sources_by_dataset"]
    require(type(prior) is dict and set(prior) == PRIOR_DATASETS
        and all(type(rows) is list and rows for rows in prior.values()), "complete named prior source inventories required")
    require(prior["paragraph_train"] == _source_rows(training_rows)
        and prior["paragraph_validation"] == _source_rows(validation_rows)
        and prior["original_train_bank"] == _source_rows(mixture["training_bank"]),
        "prior original TRAIN/development identity differs")
    original_contexts = context.validate_training_contexts(training_rows, validation_rows, source_contexts)
    dimension = original_contexts["training"]["dimension"]
    require(dimension in (384, 768) and len(training_rows) == len(validation_rows) == 48,
        "original48 native384/768 contextual cohort required")
    require(len(codec["target_vocabulary"]) == 32, "complete32V mixture codec required")
    # Rebuilding from the complete bank verifies all derivations and labels, and
    # rejects changed templates/packing. No evaluation reference is an input.
    corpus = mixture["corpus"]
    require(type(corpus) is dict and set(corpus) == {"source_rows", "references", "receipt"},
        "complete authored TRAIN corpus required")
    rebuilt = authored.build(training_bank=mixture["training_bank"], prior_sources_by_dataset=prior,
        codec=codec, sealed_recipe_sha256=corpus["receipt"]["sealed_recipe_sha256"],
        validate_rule=validate_rule, seed=corpus["receipt"]["seed"])
    require(corpus == rebuilt, "TRAIN corpus or derivations differ from original bank")
    _deadline(deadline)
    plan, production, inputs = (mixture[k] for k in ("source_plan", "production_report", "source_inputs"))
    expected_plan = producer.source_plan(corpus["source_rows"],
        expected_source_rows_sha256=corpus["receipt"]["source_rows_sha256"],
        sealed_recipe_sha256=corpus["receipt"]["sealed_recipe_sha256"])
    require(plan == expected_plan and producer.validate_report(plan, production) == dimension,
        "native TRAIN production or source plan differs")
    require(type(inputs) is dict and set(inputs) == {"schema", "complete", "role", "dimension", "rows",
        "clause_cache", "source_contexts", "production_sha256", "source_plan_sha256", "targets_attached",
        "preprocessing_fitted", "qualified", "admitted", "checkpoint_promoted", "inputs_sha256"}
        and inputs["schema"] == "training-paraphrase-source-inputs/v1" and inputs["complete"] is True
        and inputs["role"] == "train_augmentation" and inputs["dimension"] == dimension
        and all(inputs[k] is False for k in ("targets_attached", "preprocessing_fitted", "qualified", "admitted", "checkpoint_promoted"))
        and inputs["production_sha256"] == production["production_sha256"]
        and inputs["source_plan_sha256"] == plan["plan_sha256"]
        and inputs["inputs_sha256"] == digest({k: v for k, v in inputs.items() if k != "inputs_sha256"}),
        "closed native TRAIN inputs binding differs")
    vectors = {row["source_sha256"]: row["vector"] for row in production["vectors"]}
    expected_rows = [dict(row, input=vectors[authored.base.text_sha(row["source_text"])]) for row in corpus["source_rows"]]
    expected_cache, seen = [], set()
    for row in corpus["source_rows"]:
        for text in row["source_text"].split("\n\n"):
            sha = authored.base.text_sha(text)
            if sha not in seen:
                seen.add(sha)
                expected_cache.append(dict(id="clause:"+sha, source_text=text, input=vectors[sha]))
    require(inputs["rows"] == expected_rows and inputs["clause_cache"] == expected_cache
        and inputs["source_contexts"] == context.build_source_contexts(corpus["source_rows"], expected_cache),
        "native paragraph/clause vectors differ from verified source production")
    extra_rows = [dict(row, target_ids=deepcopy(ref["target_ids"]))
        for row, ref in zip(expected_rows, corpus["references"])]
    # Existing fidelity APIs require source byte digests; keep the authored
    # reference unchanged in the corpus and explicitly adapt it for training.
    extra_refs = [dict(ref, source_sha256=authored.base.text_sha(ref["source_text"])) for ref in corpus["references"]]
    effective_rows = list(training_rows)+extra_rows
    effective_refs = list(training_references)+extra_refs
    effective_contexts = dict(source_contexts["train"], **inputs["source_contexts"])
    binding = context.validate_training_contexts(effective_rows, validation_rows,
        {"train": effective_contexts, "validation": source_contexts["validation"]})
    # Enforce complete targets and original label ownership before private model
    # allocation, including scalar/boundary consumers of the effective rows.
    values.reference_source_values(effective_rows, effective_refs, codec, validate_rule=validate_rule)
    values.reference_source_values(validation_rows, validation_references, codec, validate_rule=validate_rule)
    train_ids, train_sources = core._rows(effective_rows, dimension, codec["target_vocabulary"], 512)
    eval_ids, eval_sources = core._rows(validation_rows, dimension, codec["target_vocabulary"], 512)
    require(not train_ids & eval_ids and not train_sources & eval_sources, "effective TRAIN/development overlap")
    train_texts = _texts(effective_rows)
    train_vectors = {digest(row["input"]) for row in effective_rows}
    train_vectors.update(segment["embedding_sha256"] for packet in effective_contexts.values() for segment in packet["segments"])
    eval_vectors = mixture["evaluation_vectors_by_dataset"]
    require(type(eval_vectors) is dict and set(eval_vectors) == set(EVALUATION_DATASETS),
        "all evaluation vector coverage declarations required; use explicit empty lists when unavailable")
    coverage = {}
    for name in EVALUATION_DATASETS:
        _deadline(deadline)
        texts = _texts(prior[name])
        require(not train_texts & texts and not train_ids & {row["id"] for row in prior[name]},
            "effective TRAIN overlaps evaluation source inventory: "+name)
        observed = eval_vectors[name]
        require(type(observed) is list and len(observed) <= 4096, "bounded evaluation vector inventory required")
        observed_sources = set()
        for row in observed:
            require(type(row) is dict and set(row) == {"id", "source_text", "input"}
                and type(row["id"]) is str and authored.base._normal(row["source_text"]) in texts,
                "evaluation vector source outside named source inventory")
            require(context._vector(row["input"]) == dimension and digest(row["input"]) not in train_vectors,
                "effective TRAIN overlaps evaluation vector or width differs")
            observed_sources.add(authored.base._normal(row["source_text"]))
        coverage[name] = dict(source_strings=len(texts), observed_vector_rows=len(observed),
            observed_source_strings=len(observed_sources), missing_vector_source_strings=len(texts-observed_sources),
            vector_coverage_complete=observed_sources == texts, source_exclusion_complete=True)
    require(Counter(len(row["source_text"].split("\n\n")) for row in training_rows) == {1: 12, 2: 12, 4: 12, 8: 12},
        "original count inventory differs")
    lengths = {count: {len(row["target_ids"]) for row in effective_rows
        if len(row["source_text"].split("\n\n")) == count} for count in (1, 2, 4, 8)}
    require(lengths == {1: {40}, 2: {73}, 4: {139}, 8: {271}}, "same-count full-target lengths differ")
    receipt = dict(schema=SCHEMA, policy=mixture["policy"], payload_sha256=mixture["payload_sha256"],
        dimension=dimension, original_rows_sha256=digest(training_rows), original_contexts_sha256=digest(source_contexts["train"]),
        effective_rows_sha256=digest(effective_rows), effective_references_sha256=digest(effective_refs),
        effective_contexts_sha256=digest(effective_contexts), effective_context_binding=binding,
        preparation_production_sha256=production["production_sha256"], evaluation_coverage=coverage,
        original_preprocessing_preserved=True, preprocessing_refitted=False, original_count_stream_preserved=True,
        evaluation_labels_used_to_construct_training=False, used_for_selection=False, encoder_executed=False,
        full_vocabulary_size=32, context_tokens=512, output_tokens=512, temperature=0,
        admitted=False, qualified=False, checkpoint_promoted=False, fresh_holdout=False,
        semantic_independence_established=False, caller_must_authenticate_files_and_producer_closure=True)
    _deadline(deadline)
    result = Selector(training_rows, effective_rows, effective_refs, effective_contexts, corpus["references"], receipt)
    _deadline(deadline)
    return result


class Selector:
    """Fixed alternating draws; commits and possibly aborted draws are separate."""
    def __init__(self, parents, rows, references, contexts, extra_references, receipt):
        self._parents = deepcopy(parents)
        self._rows, self._references, self._contexts = deepcopy(rows), deepcopy(references), deepcopy(contexts)
        self._by_id = {row["id"]: row for row in self._rows}
        self._parent_by_id = {row["id"]: row for row in self._parents}
        self._receipt = deepcopy(receipt)
        self._row_hash = {row["id"]: digest(row) for row in self._rows}
        self._context_hash = {key: digest(value) for key, value in self._contexts.items()}
        extra_by_id = {row["id"]: row for row in extra_references}
        self._exposure = {row["id"]: dict(template=extra_by_id[row["id"]]["template"]
            if row["id"] in extra_by_id else "original", modalities=[rule["modality"] for rule in row["target"]["rules"]],
            rules=[digest(rule) for rule in row["target"]["rules"]]) for row in self._references}
        self._template_counts, self._modality_counts, self._rule_counts = Counter(), Counter(), Counter()
        self._queues = {}
        for count in (1, 2, 4, 8):
            groups = [[r["id"] for r in extra_references if r["clause_count"] == count and r["template"] == template]
                for template in authored.TEMPLATES]
            require(all(len(group) == 6 for group in groups), "six rows per template/count required")
            groups = [sorted(group) for group in groups]
            self._queues[count] = [identity for pair in zip(*groups) for identity in pair]
        self._occurrences = Counter()
        self._cursor = Counter()
        self._draws = self._commits = self._draw_rows = self._committed_rows = self._replacements = 0
        self._committed_replacements = 0
        self._sequence, self._committed_sequence = hashlib.sha256(), hashlib.sha256()
        self._pending = None

    @property
    def effective_rows(self): return deepcopy(self._rows)

    @property
    def effective_references(self): return deepcopy(self._references)

    @property
    def effective_contexts(self): return deepcopy(self._contexts)

    def select(self, parent_batch, *, deadline):
        _deadline(deadline)
        require(self._pending is None, "previous mixture draw remains uncommitted")
        require(type(parent_batch) is list and 1 <= len(parent_batch) <= 8
            and all(type(row) is dict and row.get("id") in self._parent_by_id for row in parent_batch)
            and len({row["id"] for row in parent_batch}) == len(parent_batch), "unique original parent batch required")
        require(all(row == self._parent_by_id[row["id"]] for row in parent_batch), "mixture parent row changed")
        occurrences, cursor = self._occurrences.copy(), self._cursor.copy()
        selected, replacements = [], 0
        for parent in parent_batch:
            key = parent["id"]; count = len(parent["source_text"].split("\n\n"))
            replace = self._receipt["policy"] == "half_paraphrases" and occurrences[key] % 2 == 1
            effective = key
            if replace:
                effective = self._queues[count][cursor[count] % 12]
                cursor[count] += 1; replacements += 1
            occurrences[key] += 1
            row = self._by_id[effective]
            require(len(row["target_ids"]) == len(parent["target_ids"])
                and len(row["source_text"].split("\n\n")) == count, "mixture count/token budget differs")
            selected.append(deepcopy(row))
        require(len({row["id"] for row in selected}) == len(selected), "duplicate effective mixture batch")
        receipt = dict(draw=self._draws, parent_ids=[r["id"] for r in parent_batch], effective_ids=[r["id"] for r in selected],
            row_sha256=[self._row_hash[r["id"]] for r in selected], context_sha256=[self._context_hash[r["id"]] for r in selected],
            replacements=replacements, target_token_presentations=sum(len(r["target_ids"])-1 for r in selected),
            source_value_presentations=4*sum(len(r["source_text"].split("\n\n")) for r in selected),
            clause_counts=[len(r["source_text"].split("\n\n")) for r in selected])
        _deadline(deadline)
        self._occurrences, self._cursor = occurrences, cursor
        self._draws += 1; self._draw_rows += len(selected); self._replacements += replacements
        self._sequence.update(core._raw(receipt)); self._pending = receipt
        return selected

    def record_commit(self, step):
        require(type(step) is int and step == self._commits and self._pending is not None,
            "ordered committed mixture draw required")
        receipt = dict(self._pending, zero_based_committed_step=step)
        self._commits += 1; self._committed_rows += len(receipt["effective_ids"])
        self._committed_replacements += receipt["replacements"]
        self._committed_sequence.update(core._raw(receipt)); self._pending = None
        for identity in receipt["effective_ids"]:
            exposure = self._exposure[identity]
            self._template_counts[exposure["template"]] += 1
            self._modality_counts.update(exposure["modalities"])
            self._rule_counts.update(exposure["rules"])
        return receipt

    def snapshot(self):
        return dict(deepcopy(self._receipt), draw_batches=self._draws, committed_updates=self._commits,
            draw_rows=self._draw_rows, committed_rows=self._committed_rows,
            drawn_replacements=self._replacements, committed_replacements=self._committed_replacements,
            parent_occurrences=dict(self._occurrences), augmentation_queue_cursors=dict(self._cursor),
            committed_template_presentations=dict(self._template_counts),
            committed_modality_clause_presentations=dict(self._modality_counts),
            committed_rule_clause_presentations=dict(self._rule_counts),
            draw_sequence_sha256=self._sequence.hexdigest(), committed_sequence_sha256=self._committed_sequence.hexdigest(),
            uncommitted_draw=None if self._pending is None else deepcopy(self._pending),
            draws_may_include_uncommitted_final_batch=True)
