"""Opt-in, training-only modality supervision from the existing authored bank.

This fixed Legal fixture helper neither fits preprocessing nor invokes an
encoder, recurrent decoder, count head, optimizer, or qualification gate.
Caller-authenticated file provenance remains the runner's responsibility.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import math
import re
import time

from . import authored_scalar_holdout as authored
from . import clause_source_context as contexts
from . import decoder_distillation_experiment as core
from . import source_value_decoder_experiment as values

SCHEMA = "authored-training-modality-bank/v1"
CACHE_SCHEMA = "cached-training-modality-bank/v1"
LOSS_SCHEMA = "training-source-modality-auxiliary/v1"
STRATA = tuple((modality, style) for modality in ("O", "P", "F") for style in (0, 1))
FORBIDDEN_SPLITS = ("validation", "test", "canary", "exposed_holdout")
INPUT_NAMES = {"source_rows", "references", "paragraph_training_rows", "forbidden_rows_by_split", "codec"}
BATCH_SIZE = 6
FALSE = dict(admitted=False, qualified=False, proof_authority=False, lake_executed=False,
    source_semantics_verified=False, formalized=False, roundtrip_ok=False,
    checkpoint_promoted=False, selection_performed=False, historical_linguistic_teacher_modified=False)
_require = core._require
digest = core.digest


def _deadline(deadline):
    _require(type(deadline) in (int, float) and math.isfinite(deadline), "finite modality deadline required")
    if time.monotonic() >= deadline:
        raise TimeoutError("source modality auxiliary deadline")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normal(text):
    return " ".join(text.casefold().split())


def _source(text, style):
    _require(type(text) is str and 0 < len(text) <= 512 and type(style) is int and style in (0, 1),
             "exact bounded authored source and wording style required")
    phrases = ({"O": "must", "P": "may", "F": "must not"},
               {"O": "is required to", "P": "is allowed to", "F": "is forbidden to"})[style]
    for modality, phrase in phrases.items():
        pattern = r"The ("+"|".join(authored.ACTORS)+") "+re.escape(phrase)
        pattern += " ("+"|".join(authored.ACTIONS)+") the ("+"|".join(authored.OBJECTS)+r")\."
        match = re.fullmatch(pattern, text)
        if match:
            actor, action, object_ = match.groups()
            return dict(actor=actor, action=action, modality=modality, object=object_,
                        conditions=[], exceptions=[], temporal=[])
    raise ValueError("source/wording style is not one of the six original active Legal templates")


def _vector(vector):
    _require(type(vector) is list and len(vector) in (8, 384, 768), "supported source vector width required")
    core._vector(vector, len(vector))
    _require(abs(math.fsum(float(v)*float(v) for v in vector)-1.) <= 1e-4, "normalized source vector required")
    return len(vector)


def _identity(row):
    _require(type(row["id"]) is str and 0 < len(row["id"]) <= 1024, "bounded source ID required")


def adapt_original_training_bank(original_rows, cache_rows, *, codec, deadline):
    """Join authenticated original rows/cache by exact ID; never infer labels.

    The runner pins the original files before passing their parsed rows. This
    adapter authenticates their internal text/vector/target/style agreement.
    """
    _deadline(deadline); authored._codec(codec)
    _require(type(original_rows) is list and type(cache_rows) is list
             and len(original_rows) == len(cache_rows) == 180, "complete original180 training/cache rows required")
    originals = {}
    for row in original_rows:
        _require(type(row) is dict and {"id", "source_text", "embedding", "target", "wording_style", "split"} <= set(row)
                 and row["split"] == "train", "declared original training rows only")
        _identity(row); _vector(row["embedding"])
        _require(row["id"] not in originals, "duplicate original training ID")
        target = {"rules": [_source(row["source_text"], row["wording_style"])]}
        _require(row["target"] == target, "original source/style/reference disagreement")
        originals[row["id"]] = row
    sources, references, seen = [], [], set()
    for cached in cache_rows:
        _deadline(deadline)
        _require(type(cached) is dict and set(cached) == {"id", "source_text", "input", "target_ids"}, "closed original cache row required")
        _identity(cached); _vector(cached["input"])
        row = originals.get(cached["id"])
        _require(row is not None and cached["id"] not in seen and row["source_text"] == cached["source_text"]
                 and row["embedding"] == cached["input"], "cache ID/source/vector differs from original training data")
        _require(cached["target_ids"] == authored._encode(row["target"], codec), "complete cached target IDs differ")
        seen.add(cached["id"])
        sources.append(dict(id=row["id"], source_text=row["source_text"], input=deepcopy(cached["input"]), wording_style=row["wording_style"]))
        references.append(dict(id=row["id"], target=deepcopy(row["target"])))
    result = dict(source_rows=sources, references=references, receipt=dict(
        original_rows_sha256=digest(original_rows), cache_rows_sha256=digest(cache_rows), codec_sha256=digest(codec),
        source_rows_sha256=digest(sources), references_sha256=digest(references), rows=180,
        alignment="exact ID/text/vector/full target IDs; declared train split; six literal authored templates",
        file_provenance_verified_by_helper=False, **FALSE))
    _deadline(deadline)
    return result


def prepare_bank(source_rows, references, *, paragraph_training_rows, forbidden_rows_by_split,
                 codec, bank_kind, input_sha256, validate_rule, deadline):
    """Prepare either113 paragraph-used clauses or all180 original train clauses.

    Forbidden rows contain sources and vectors only. They may include both
    paragraph and clause rows; overlap is rejected by ID, normalized text, and
    exact vector digest. No forbidden labels are accepted or inspected.
    """
    _deadline(deadline); authored._codec(codec)
    _require(bank_kind in ("used113", "full180"), "explicit existing training-bank choice required")
    _require(type(source_rows) is list and type(references) is list and len(source_rows) == len(references) == 180,
             "complete original180 source/reference bank required")
    _require(type(paragraph_training_rows) is list and len(paragraph_training_rows) == 48, "original48 training paragraphs required")
    _require(type(forbidden_rows_by_split) is dict and set(forbidden_rows_by_split) == set(FORBIDDEN_SPLITS), "all four explicit forbidden source inventories required")
    _require(type(input_sha256) is dict and set(input_sha256) == INPUT_NAMES, "closed input digest envelope required")
    _require(callable(validate_rule), "explicit complete-rule validator required")
    blocked_ids, blocked_text, blocked_vectors = set(), set(), set()
    forbidden_count = 0
    for split in FORBIDDEN_SPLITS:
        rows = forbidden_rows_by_split[split]
        _require(type(rows) is list and 1 <= len(rows) <= 4096, "nonempty bounded forbidden inventory required")
        forbidden_count += len(rows)
        _require(forbidden_count <= 8192, "forbidden inventory exceeds bound")
        for row in rows:
            _deadline(deadline)
            _require(type(row) is dict and set(row) == {"id", "source_text", "input"}, "closed forbidden source-only row required")
            _identity(row); _vector(row["input"])
            _require(type(row["source_text"]) is str and 0 < len(row["source_text"]) <= 32768, "bounded forbidden source required")
            blocked_ids.add(row["id"]); blocked_text.add(_normal(row["source_text"])); blocked_vectors.add(digest(row["input"]))
            blocked_text.update(_normal(piece) for piece in row["source_text"].split("\n\n"))
    labels = {}; targets = {}
    for ref in references:
        _deadline(deadline)
        _require(type(ref) is dict and set(ref) == {"id", "target"}, "closed original training reference required")
        _identity(ref)
        _require(ref["id"] not in labels, "duplicate training reference ID")
        authored._rules(ref["target"], validate_rule)
        _require(len(ref["target"]["rules"]) == 1, "one complete rule per auxiliary source required")
        labels[ref["id"]] = ref["target"]["rules"][0]; targets[ref["id"]] = digest(ref["target"])
    rows = []; ids, texts, widths = set(), set(), set(); strata = Counter(); cells = Counter()
    for row in source_rows:
        _deadline(deadline)
        _require(type(row) is dict and set(row) == {"id", "source_text", "input", "wording_style"}, "closed original training source/cache row required")
        _identity(row); widths.add(_vector(row["input"]))
        rule = _source(row["source_text"], row["wording_style"])
        _require(row["id"] in labels and labels[row["id"]] == rule, "complete source/style/reference alignment differs")
        text = _normal(row["source_text"]); vector_sha = digest(row["input"])
        _require(row["id"] not in ids and text not in texts, "unique original training source identities required")
        _require(row["id"] not in blocked_ids and text not in blocked_text and vector_sha not in blocked_vectors,
                 "original training bank overlaps supplied forbidden source/vector inventory")
        ids.add(row["id"]); texts.add(text)
        strata[rule["modality"], row["wording_style"]] += 1
        cells[rule["actor"], rule["action"], rule["object"], rule["modality"], row["wording_style"]] += 1
        rows.append(dict(row, input=deepcopy(row["input"]), source_sha256=_sha(row["source_text"]),
            input_sha256=vector_sha, target_sha256=targets[row["id"]], modality=rule["modality"],
            modality_token_id=codec["target_vocabulary"].index('"'+rule["modality"]+'"')))
    _require(len(widths) == 1 and set(labels) == ids and strata == Counter({k: 30 for k in STRATA})
             and len(cells) == 180 and all(v == 1 for v in cells.values()), "complete balanced original180 inventory required")
    used, paragraph_ids, paragraph_texts, lengths = set(), set(), set(), Counter()
    for row in paragraph_training_rows:
        _require(type(row) is dict and set(row) == {"id", "source_text"}, "closed source-only training paragraphs required")
        _identity(row)
        _require(type(row["source_text"]) is str and len(row["source_text"]) <= 32768, "bounded training paragraph required")
        pieces = row["source_text"].split("\n\n"); length = len(pieces)
        _require(length in (1, 2, 4, 8) and row["id"] not in paragraph_ids
                 and _normal(row["source_text"]) not in paragraph_texts, "unique original training paragraphs required")
        _require(row["id"] not in blocked_ids and _normal(row["source_text"]) not in blocked_text, "training paragraph overlaps forbidden inventory")
        _require(all(_normal(piece) in texts for piece in pieces), "training paragraph clause missing from original bank")
        used.update(_sha(piece) for piece in pieces); paragraph_ids.add(row["id"]); paragraph_texts.add(_normal(row["source_text"])); lengths[length] += 1
    _require(lengths == Counter({1:12, 2:12, 4:12, 8:12}) and len(used) == 113
             and used <= {row["source_sha256"] for row in rows}, "exact original48/113 training source inventory required")
    supplied = dict(source_rows=source_rows, references=references, paragraph_training_rows=paragraph_training_rows,
                    forbidden_rows_by_split=forbidden_rows_by_split, codec=codec)
    _require(all(type(input_sha256[k]) is str and input_sha256[k] == digest(v) for k, v in supplied.items()), "authenticated input digest differs")
    chosen = [row for row in rows if bank_kind == "full180" or row["source_sha256"] in used]
    counts = Counter((row["modality"], row["wording_style"]) for row in chosen)
    _require(set(counts) == set(STRATA) and min(counts.values()) >= 1, "all six active training strata required")
    result = dict(schema=SCHEMA, bank_kind=bank_kind, dimension=next(iter(widths)), rows=chosen,
        full_bank_rows=180, paragraph_used_unique_sources=113, selected_rows=len(chosen), codec_sha256=digest(codec),
        input_sha256=dict(input_sha256), strata=[dict(modality=m, wording_style=s, count=counts[m,s]) for m,s in STRATA],
        forbidden_inventory_counts={k:len(v) for k,v in forbidden_rows_by_split.items()},
        source_inventory=[dict(id=row["id"], source_sha256=row["source_sha256"], input_sha256=row["input_sha256"],
                              target_sha256=row["target_sha256"], modality=row["modality"], wording_style=row["wording_style"]) for row in chosen],
        file_provenance_verified_by_helper=False, preparation_scope="hash-bound caller-supplied original training artifacts",
        new_sources_authored=False, encoder_executed=False, normalization_fitted=False,
        forbidden_reference_labels_accessed=False, **FALSE)
    result["bank_sha256"] = digest(result); _deadline(deadline)
    return result


def estimate_training_work_bytes(bank, *, max_optimizer_steps):
    """Conservative tensor/retained-receipt estimate before allocating a cache."""
    _require(type(bank) is dict and bank.get("schema") == SCHEMA and bank.get("bank_kind") in ("used113", "full180"), "prepared Legal bank required")
    _require(type(bank.get("dimension")) is int and bank["dimension"] in (8,384,768)
             and type(bank.get("selected_rows")) is int and bank["selected_rows"] == (113 if bank["bank_kind"] == "used113" else 180), "bounded bank dimensions required")
    _require(type(max_optimizer_steps) is int and 1 <= max_optimizer_steps <= 100000, "bounded committed-step budget required")
    n, d = bank["selected_rows"], bank["dimension"]
    return (n*d*64 + n*(9*d*4+8+8) + 6*8*4*32*4*8
            + max_optimizer_steps*6*(32*40+4096) + 1048576)


def validate_training_binding(bank, training_rows, validation_rows, *, source_contexts, codec, deadline):
    """Bind a prepared bank to this fit's actual source-only cohort and cache.

    Extra full180 sources remain externally authenticated training data. This
    check binds the113 paragraph-used sources and rejects actual validation
    overlap; it does not inspect reference labels or certify other split files.
    """
    _deadline(deadline); authored._codec(codec)
    estimate_training_work_bytes(bank, max_optimizer_steps=1)
    _require(bank.get("bank_sha256") == digest({k:v for k,v in bank.items() if k != "bank_sha256"})
             and bank.get("codec_sha256") == digest(codec), "prepared bank digest/codec differs")
    closed = {}
    for role, rows in (("train", training_rows), ("validation", validation_rows)):
        _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded actual source rows required")
        closed[role] = []
        for row in rows:
            _deadline(deadline)
            _require(type(row) is dict and {"id", "source_text", "input"} <= set(row), "actual source identity/vector required")
            _identity(row); dimension = _vector(row["input"])
            _require(dimension == bank["dimension"], "actual paragraph/bank dimension differs")
            closed[role].append(dict(id=row["id"], source_text=row["source_text"], input=row["input"]))
    train_sources = [{k:row[k] for k in ("id", "source_text")} for row in closed["train"]]
    _require(len(train_sources) == 48 and digest(train_sources) == bank["input_sha256"]["paragraph_training_rows"],
             "actual training paragraph inventory differs from prepared bank")
    context_receipt = contexts.validate_training_contexts(closed["train"], closed["validation"], source_contexts)
    _require(context_receipt["training"]["dimension"] == bank["dimension"], "actual clause/bank dimension differs")
    rows = bank["rows"]
    _require(type(rows) is list and len(rows) == bank["selected_rows"], "prepared bank row count differs")
    by_sha = {}
    for row in rows:
        _deadline(deadline)
        _require(type(row) is dict and row.get("source_sha256") == _sha(row["source_text"])
                 and row.get("input_sha256") == digest(row["input"]), "prepared bank source/vector identity differs")
        _require(row["source_sha256"] not in by_sha, "duplicate bank literal source")
        by_sha[row["source_sha256"]] = row
    actual_used = {}
    for row in closed["train"]:
        for segment in source_contexts["train"][row["id"]]["segments"]:
            _deadline(deadline)
            sha = segment["source_sha256"]
            found = by_sha.get(sha)
            _require(found is not None and found["source_text"] == segment["source_text"]
                     and found["input"] == segment["vector"] and found["input_sha256"] == segment["embedding_sha256"],
                     "actual training clause/vector differs from prepared bank")
            actual_used[sha] = segment["embedding_sha256"]
    _require(len(actual_used) == 113, "actual training source inventory must contain113 unique clauses")
    blocked_ids, blocked_text, blocked_vectors = set(), set(), set()
    for row in closed["validation"]:
        blocked_ids.add(row["id"]); blocked_text.add(_normal(row["source_text"])); blocked_vectors.add(digest(row["input"]))
        for segment in source_contexts["validation"][row["id"]]["segments"]:
            blocked_ids.add("clause:"+segment["source_sha256"])
            blocked_text.add(_normal(segment["source_text"])); blocked_vectors.add(segment["embedding_sha256"])
    _require(all(row["id"] not in blocked_ids and _normal(row["source_text"]) not in blocked_text
                 and row["input_sha256"] not in blocked_vectors for row in rows),
             "prepared auxiliary bank overlaps actual validation sources/vectors")
    receipt = dict(schema="source-modality-training-binding/v1", bank_sha256=bank["bank_sha256"],
        bank_kind=bank["bank_kind"], dimension=bank["dimension"], codec_sha256=digest(codec),
        training_rows_sha256=digest(closed["train"]), validation_rows_sha256=digest(closed["validation"]),
        training_paragraph_sources_sha256=digest(train_sources),
        training_contexts_sha256=digest(source_contexts["train"]), validation_contexts_sha256=digest(source_contexts["validation"]),
        actual_training_clause_vectors_sha256=digest(actual_used), actual_training_unique_clauses=len(actual_used),
        selected_bank_rows=len(rows), externally_declared_extra_training_sources=len(rows)-len(actual_used),
        validation_labels_accessed=False, training_reference_labels_accessed=False,
        other_forbidden_split_authentication="caller-authenticated preparation inventories; not reloaded here", **FALSE)
    _deadline(deadline)
    return receipt


class _TensorCache:
    __slots__ = ("_model", "_data", "_vectors", "_mask", "_targets", "_orders", "_rows", "_fixed", "_versions", "_receipt", "_max_steps",
                 "_sampler", "_content_groups", "_matched_bound")

    def __setattr__(self, name, value):
        raise AttributeError("prepared modality cache is immutable")

    @property
    def receipt(self):
        return deepcopy(self._receipt)


def prepare_tensor_cache(torch, model, bank, *, codec, input_transform, seed, deadline, max_optimizer_steps=340,
                         sampler="independent"):
    """Cache sources; optionally group complete cycles by authored content.

    Matched cycles require the complete180 bank: each of30 actor/action/object
    groups must contain exactly the six modality/style variants. Only complete
    30-update cycles are matched; the final incomplete cycle uses the original
    independent sampler at its original committed-step indices. This preserves
    every source's full-budget exposure, without advancing a mutable cursor.
    """
    started = time.monotonic(); _deadline(deadline)
    estimate = estimate_training_work_bytes(bank, max_optimizer_steps=max_optimizer_steps)
    _require(type(sampler) is str and sampler in ("independent", "content_matched_cycles"),
             "unknown auxiliary source-modality sampler")
    matched = sampler == "content_matched_cycles"
    _require(not matched or bank["bank_kind"] == "full180", "content-matched sampling requires the complete full180 bank")
    authored._codec(codec)
    _require(type(seed) is int and 0 <= seed <= 2**31-1, "bounded explicit auxiliary sampler seed required")
    _require(bank.get("bank_sha256") == digest({k:v for k,v in bank.items() if k != "bank_sha256"})
             and bank["codec_sha256"] == digest(codec), "prepared bank digest/codec differs")
    description = model.describe()
    if description.get("schema") == "ordered-clause-recurrent-source-decoder-development/v1":
        from . import ordered_clause_recurrent_decoder_experiment as owner
    elif description.get("schema") == "action-factorized-clause-source-decoder-development/v1":
        from . import action_factorized_clause_decoder_experiment as owner
    else:
        raise ValueError("explicit factorized or ordered-recurrent source model required")
    owner.checked_specification(model, codec)
    _require(model.dimension == bank["dimension"], "bank/model dimension differs")
    rows = bank["rows"]
    _require(type(rows) is list and len(rows) == bank["selected_rows"], "bank rows differ")
    identities, texts, strata = set(), set(), {key:[] for key in STRATA}
    content = {}
    for index, row in enumerate(rows):
        _deadline(deadline)
        rule = _source(row["source_text"], row["wording_style"]); _identity(row); _vector(row["input"])
        _require(len(row["input"]) == model.dimension and row["id"] not in identities and row["source_text"] not in texts,
                 "cache source dimensions/identities differ")
        _require(row["source_sha256"] == _sha(row["source_text"]) and row["input_sha256"] == digest(row["input"])
                 and row["target_sha256"] == digest({"rules":[rule]}) and row["modality"] == rule["modality"]
                 and type(row["modality_token_id"]) is int
                 and row["modality_token_id"] == codec["target_vocabulary"].index('"'+rule["modality"]+'"'), "cache source/reference digest differs")
        identities.add(row["id"]); texts.add(row["source_text"]); strata[row["modality"],row["wording_style"]].append(index)
        if matched:
            # Derive content from the authenticated literal source, never a
            # paragraph position, held-out label, or caller-supplied group tag.
            key = tuple(rule[field] for field in ("actor", "action", "object"))
            members = content.setdefault(key, {})
            stratum = (rule["modality"], row["wording_style"])
            _require(stratum not in members, "duplicate content/modality/style variant")
            members[stratum] = index
    _require(all(strata.values()), "cache requires six nonempty strata")
    groups = ()
    matched_bound = 0
    if matched:
        _require(len(rows) == 180 and len(content) == 30
                 and all(set(members) == set(STRATA) for members in content.values()),
                 "content-matched sampling requires30 complete six-variant source groups")
        groups = tuple((key, tuple(content[key][stratum] for stratum in STRATA))
                       for key in sorted(content, key=lambda key: digest([seed, "content_matched_cycles", key])))
        matched_bound = (max_optimizer_steps // len(groups)) * len(groups)
        _deadline(deadline)
    sources = [dict(id=row["id"], source_text=row["source_text"]) for row in rows]
    cached = [dict(source, input=row["input"]) for source,row in zip(sources,rows)]
    source_contexts = contexts.build_source_contexts(sources,cached)
    packet = contexts.batch_source_context(torch,sources,source_contexts,input_transform)
    data = torch.tensor([row["input"] for row in rows],dtype=torch.float32)
    data = (data-torch.tensor(input_transform["mean"],dtype=torch.float32))/input_transform["scale"]
    targets = torch.tensor([row["modality_token_id"] for row in rows],dtype=torch.long)
    orders = tuple(tuple(sorted(strata[key],key=lambda i:digest([seed,key,rows[i]["source_sha256"],rows[i]["id"]]))) for key in STRATA)
    fixed = [(name, value, value._version) for name,value in model.named_buffers()]
    fixed += [(name, value, value._version) for name,value in model.named_parameters() if not value.requires_grad]
    _require(fixed, "frozen preprocessing/identity projection required")
    tensors = (data,packet["vectors"],packet["mask"],targets)
    _require(all(not t.requires_grad for t in tensors), "cached inputs/targets must remain detached")
    receipt = dict(schema=CACHE_SCHEMA,bank_sha256=bank["bank_sha256"],bank_kind=bank["bank_kind"],dimension=model.dimension,
        selected_rows=len(rows),strata=deepcopy(bank["strata"]),seed=seed,batch_size=6,max_optimizer_steps=max_optimizer_steps,
        input_transform_sha256=digest(input_transform),codec_sha256=digest(codec),estimated_training_work_bytes=estimate,
        cached_tensor_bytes=sum(t.numel()*t.element_size() for t in tensors),source_only_contexts_sha256=digest(source_contexts),
        sampling="one source per modality/style stratum; independently hash-ordered cyclic lists indexed by committed step",
        full_vocabulary_size=32,loss_field="modality",source_slot=0,normalization_fitted=False,encoder_executed=False,
        recurrent_forward_executed=False,count_forward_executed=False,model_copied=False,
        per_step_bank_rehash=False,elapsed_seconds=time.monotonic()-started,**FALSE)
    if matched:
        group_receipt = [dict(actor=key[0], action=key[1], object=key[2], indices=list(indices)) for key,indices in groups]
        receipt.update(sampler_policy=sampler, content_group_count=len(groups),
            content_group_order=group_receipt, content_group_order_sha256=digest(group_receipt),
            matched_update_bound=matched_bound, independent_remainder_updates=max_optimizer_steps-matched_bound,
            sampling="complete hash-ordered content cycles; final incomplete cycle retains original independent step indices",
            full_budget_per_source_exposure_matches_independent=True)
    cache = _TensorCache()
    for name,value in dict(_model=model,_data=data,_vectors=packet["vectors"],_mask=packet["mask"],_targets=targets,
        _orders=orders,_rows=tuple((row["id"],row["source_sha256"],row["modality"],row["wording_style"]) for row in rows),
        _fixed=tuple(fixed),_versions=tuple(t._version for t in tensors),_receipt=receipt,_max_steps=max_optimizer_steps,
        _sampler=sampler,_content_groups=groups,_matched_bound=matched_bound).items():
        object.__setattr__(cache,name,value)
    _deadline(deadline)
    return cache


def select_indices(cache, committed_step):
    """Pure selection: retrying the same uncommitted update chooses the same6."""
    _require(type(cache) is _TensorCache and type(committed_step) is int and 0 <= committed_step < cache._max_steps,
             "bounded committed update index and prepared cache required")
    if cache._sampler == "content_matched_cycles" and committed_step < cache._matched_bound:
        return cache._content_groups[committed_step % len(cache._content_groups)][1]
    return tuple(order[committed_step % len(order)] for order in cache._orders)


def modality_loss(torch, model, cache, *, committed_step, deadline):
    """One raw source-head forward; full32V CE, no optimizer/backward call."""
    started = time.monotonic(); _deadline(deadline)
    indices = select_indices(cache,committed_step)
    _require(model is cache._model, "cache belongs to a different model instance")
    _require(tuple(t._version for t in (cache._data,cache._vectors,cache._mask,cache._targets)) == cache._versions,
             "private cached source tensors changed")
    current = dict(model.named_buffers());current.update(dict(model.named_parameters()))
    _require(all(current.get(name) is value and value._version == version for name,value,version in cache._fixed),
             "frozen model preprocessing/projection changed")
    chosen = torch.tensor(indices,dtype=torch.long)
    data = cache._data.index_select(0,chosen)
    packet = dict(vectors=cache._vectors.index_select(0,chosen),mask=cache._mask.index_select(0,chosen))
    projected = model.project(data)
    logits = model.source_value_logits(projected,source_context=packet)
    _require(isinstance(logits,torch.Tensor) and logits.dtype == torch.float32 and logits.device.type == "cpu"
             and tuple(logits.shape) == (6,8,4,32) and core._finite(torch,logits), "finite full-vocabulary source logits required")
    selected = logits[:,0,values.SOURCE_FIELDS.index("modality")]
    targets = cache._targets.index_select(0,chosen)
    row_losses = torch.nn.functional.cross_entropy(selected,targets,reduction="none")
    loss = row_losses.mean()
    _require(loss.requires_grad and core._finite(torch,loss), "finite differentiable source modality CE required")
    observed = selected.detach().tolist(); target_ids = targets.tolist(); per_row = row_losses.detach().tolist()
    receipt = dict(schema=LOSS_SCHEMA,bank_sha256=cache._receipt["bank_sha256"],bank_kind=cache._receipt["bank_kind"],
        committed_step=committed_step,sampler_seed=cache._receipt["seed"],batch_size=6,indices=list(indices),
        row_ids=[cache._rows[i][0] for i in indices],source_sha256=[cache._rows[i][1] for i in indices],
        strata=[dict(modality=cache._rows[i][2],wording_style=cache._rows[i][3]) for i in indices],
        target_token_ids=target_ids,full_vocabulary_logits=observed,per_row_cross_entropy=per_row,
        mean_cross_entropy=float(loss.detach()),correct=sum(max(range(32),key=row.__getitem__)==target for row,target in zip(observed,target_ids)),
        aggregation="mean over six full-vocabulary clause losses",loss_field="modality",source_slot=0,full_vocabulary_size=32,
        source_head_forward_calls=1,recurrent_forward_calls=0,count_forward_calls=0,encoder_forward_calls=0,
        labels_passed_to_model=False,validation_labels_used=False,normalization_fitted=False,model_copied=False,
        bank_rehashed=False,sampler_state_advanced=False,elapsed_seconds=time.monotonic()-started,**FALSE)
    if cache._sampler == "content_matched_cycles":
        matched = committed_step < cache._matched_bound
        receipt.update(sampler_policy=cache._sampler, matched_update_bound=cache._matched_bound,
                       sampling_mode="content_matched" if matched else "independent_remainder")
        if matched:
            group_index = committed_step % len(cache._content_groups)
            content = cache._content_groups[group_index][0]
            receipt.update(content_group_index=group_index, content_cycle_index=committed_step//len(cache._content_groups),
                           content_group=dict(zip(("actor", "action", "object"), content)))
    _deadline(deadline)
    return dict(loss=loss,receipt=receipt)
