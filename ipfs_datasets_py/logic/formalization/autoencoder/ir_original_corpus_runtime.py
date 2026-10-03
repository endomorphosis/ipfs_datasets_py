"""Explicit original Domain checkpoint corpus replay, without cache conversion.

Preparation authenticates the package's authored corpus and exact checkpoint
fitting manifests, using stdlib metadata only. It forwards only original IDs,
source text and vectors. Targets and native evidence remain evaluator-side.
Opening uses the existing fixed loader; neither replay nor source membership
qualifies source-disjoint model quality, a teacher, proof, stores or releases.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path

from . import checkpoint_hub as hub
from . import ir_cell_routing as routing
from . import ir_cell_runtime as cached
from . import ir_cell_target_compatibility as lexical

SCHEMA = "ir-original-corpus-runtime-plan/v1"
MAX_REFERENCE_BYTES = cached.MAX_REFERENCE_BYTES
MAX_CORPUS_ROWS = 4096
CORPUS_FILE = "authored-corpus.json"
_FAMILIES = ("intent_ir", "security_ir")
_SPLITS = ("train", "validation", "test")
_CORPUS_FIELDS = {"domain", "embedding_dimension", "embedding_model", "embedding_revision",
    "proof_authority", "real_world_corpus_used", "rows", "schema",
    "semantic_target_overlap_across_partitions", "source_license", "source_semantics_verified",
    "split_scope", "splits"}
_ROW_FIELDS = {"id", "source_text", "source_sha256", "embedding", "embedding_sha256",
               "group_id", "split", "target", "native_evidence"}
_AUTHORITY = {**cached._AUTHORITY, "native_grammar_verified": False,
    "checkpoint_numerically_validated": False, "independent_evaluation_qualified": False,
    "embedding_producer_execution_authenticated": False}


class OriginalCorpusRuntimeError(cached.IRCellRuntimeError):
    """Invalid original package/corpus association, selection or changed bytes."""


def _require(condition, message):
    if not condition:
        raise OriginalCorpusRuntimeError(message)


def _options(directory_plan_pin, inventory_pins, request, package_manifest_pin,
             corpus_pin, corpus_split, row_ids, max_reference_bytes):
    options = cached._capture_options(directory_plan_pin, inventory_pins, request,
        package_manifest_pin, corpus_split, row_ids, max_reference_bytes)
    _require(options["request"]["ir_family_id"] in _FAMILIES and options["cache_split"] in _SPLITS,
             "original corpus replay requires explicit Intent/Security 384D train/validation/test")
    options["corpus_pin"] = routing._pin(corpus_pin, max_reference_bytes)
    options["corpus_split"] = options.pop("cache_split")
    return options


def _manifest_row(row):
    return {**{key: row[key] for key in ("id", "source_sha256", "embedding_sha256")},
            "target_sha256": hashlib.sha256(cached._raw(row["target"])).hexdigest()}


def _rows(corpus, checkpoint, family, split, row_ids, corpus_pin):
    _require(set(corpus) == _CORPUS_FIELDS and corpus["schema"] == "authored-native-384-development-corpus/v1"
             and corpus["domain"] == family, "closed original corpus identity required")
    _require(type(corpus["embedding_dimension"]) is int and corpus["embedding_dimension"] == 384
             and corpus["embedding_model"] == hub.EMBEDDING["model_id"]
             and corpus["embedding_revision"] == hub.EMBEDDING["revision"], "original embedding declaration differs")
    _require(corpus["proof_authority"] is False and corpus["source_semantics_verified"] is False
             and corpus["real_world_corpus_used"] is False
             and type(corpus["semantic_target_overlap_across_partitions"]) is bool,
             "original development corpus cannot grant source/proof authority")
    for name in ("source_license", "split_scope"):
        cached._text(corpus[name], 4096, name)
    counts = corpus["splits"]
    _require(type(counts) is dict and set(counts) == set(_SPLITS)
             and all(type(value) is int and 1 <= value <= MAX_CORPUS_ROWS for value in counts.values()),
             "closed positive original split counts required")
    rows = corpus["rows"]
    _require(type(rows) is list and 1 <= len(rows) <= MAX_CORPUS_ROWS
             and sum(counts.values()) == len(rows), "bounded original corpus rows required")
    profile = lexical._profile(checkpoint, family)
    vocabulary = set(profile["vocabulary"])
    by_id, observed_counts, manifests = {}, dict.fromkeys(_SPLITS, 0), {key: [] for key in _SPLITS}
    for index, row in enumerate(rows):
        _require(type(row) is dict and set(row) == _ROW_FIELDS, "closed original authored row required")
        cached._text(row["id"], 256, "original row id")
        cached._text(row["group_id"], 256, "original group id")
        _require(row["id"] not in by_id and type(row["split"]) is str and row["split"] in _SPLITS,
                 "unique original row id and explicit split required")
        _require(type(row["target"]) is dict and type(row["native_evidence"]) is dict,
                 "original target and evidence envelopes required")
        source = cached._text(row["source_text"], 16384, "original source text")
        _require(len(source) <= 65536 and cached._hash(row["source_sha256"])
                 and hashlib.sha256(source).hexdigest() == row["source_sha256"], "original source digest differs")
        vector = row["embedding"]
        _require(type(vector) is list and len(vector) == 384, "original 384-element vector required")
        try:
            finite = all(type(value) in (int, float) and math.isfinite(value) for value in vector)
        except OverflowError:
            finite = False
        _require(finite and cached._hash(row["embedding_sha256"])
                 and hashlib.sha256(cached._raw(vector)).hexdigest() == row["embedding_sha256"],
                 "original vector numbers or canonical digest differ")
        pieces, _ = lexical._pieces(row["target"], family)
        _require(len(pieces) <= profile["max_target_tokens"] and len(pieces) - 2 <= profile["max_lexical_tokens"]
                 and all(piece in vocabulary for piece in pieces), "original corpus target is outside stored codec")
        observed_counts[row["split"]] += 1
        manifests[row["split"]].append(_manifest_row(row))
        by_id[row["id"]] = index, row
    _require(observed_counts == counts, "original declared split counts differ")
    for name, subset in (("training_manifest", "train"), ("validation_manifest", "validation")):
        _require(type(checkpoint.get(name)) is list and cached._raw(checkpoint[name]) == cached._raw(manifests[subset]),
                 "checkpoint original " + name + " differs from complete ordered corpus")
    _require(all(identifier in by_id and by_id[identifier][1]["split"] == split for identifier in row_ids),
             "selected rows must belong to exact original corpus split")
    inputs, receipts = [], []
    for identifier in row_ids:
        index, row = by_id[identifier]
        inputs.append({key: deepcopy(row[key]) for key in ("id", "source_text", "embedding")})
        receipts.append({**_manifest_row(row), "group_id": row["group_id"], "split": split,
            "row_index": index, "corpus_receipt": dict(corpus_pin),
            "checkpoint_fitting_membership": split == "train",
            "checkpoint_validation_membership": split == "validation", "native_grammar_verified": False})
    return inputs, receipts, dict(total_rows=len(rows), split_counts=counts,
        canonical_encoding_covered_rows=len(rows), training_manifest_exact=True,
        validation_manifest_exact=True, semantic_target_overlap_declared=corpus["semantic_target_overlap_across_partitions"]), profile["source_receipts"]


def prepare_ir_original_corpus_runtime(directory_plan_pin, inventory_pins, request, *,
        package_manifest_pin, corpus_pin, corpus_split, row_ids, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Authenticate exact package fitting assets; never load models or convert rows.

    Twelve cell inventories still bind checkpoint identity. The package's own
    authored corpus is an explicit, separately authenticated lane. Native-v3
    caches neither supply inputs nor substitute for original fitting examples.
    """
    try:
        options = _options(directory_plan_pin, inventory_pins, request, package_manifest_pin,
                           corpus_pin, corpus_split, row_ids, max_reference_bytes)
        route = routing.resolve_ir_cell_route(options["directory_plan_pin"], options["inventory_pins"],
            options["request"], max_reference_bytes=options["max_reference_bytes"])
        checkpoint_pin = route["selected_checkpoint"]["receipt"]
        _require(route["availability"]["checkpoint_bytes"] == "verified"
                 and route["selected_checkpoint"].get("payload_ir_family", options["request"]["ir_family_id"]) == options["request"]["ir_family_id"],
                 "available same-family original checkpoint required")
        manifest = hub.validate_manifest(cached._json(options["package_manifest_pin"], node_limit=100000),
                                         domain=options["request"]["ir_family_id"])
        parent = Path(options["package_manifest_pin"]["path"]).parent
        files = {name: routing._pin({"path": str(parent / name), **entry}, options["max_reference_bytes"])
                 for name, entry in manifest["files"].items()}
        _require(files[manifest["checkpoint_file"]] == checkpoint_pin,
                 "package checkpoint must equal exact declared cell path, bytes and SHA256")
        _require(files.get(CORPUS_FILE) == options["corpus_pin"],
                 "explicit original corpus must be the exact package authored-corpus.json")
        for pin in files.values():
            routing._read_pin(pin)
        checkpoint = cached._json(checkpoint_pin, node_limit=4_000_000)
        corpus = cached._json(options["corpus_pin"], node_limit=4_000_000)
        inputs, receipts, membership, source_receipts = _rows(corpus, checkpoint,
            options["request"]["ir_family_id"], options["corpus_split"], options["row_ids"], options["corpus_pin"])
        return deepcopy(dict(schema=SCHEMA, route=route, package_manifest_receipt=options["package_manifest_pin"],
            package_manifest=manifest, package_file_receipts=files, corpus_receipt=options["corpus_pin"],
            corpus_split=options["corpus_split"], row_ids=options["row_ids"], inputs=inputs,
            row_receipts=receipts, original_corpus_membership=membership, codec_source_receipts=source_receipts,
            capability=dict(id="experimental_original_domain384_corpus_replay/v1",
                family=options["request"]["ir_family_id"], dimension=384, dimension_role="input_embedding",
                task_id="source_to_native_ir", source_access="original_source_text_and_cached_embeddings",
                targets_forwarded_to_model=False, native_evidence_forwarded_to_model=False,
                new_source_inputs_supported=False, new_embeddings_generated=False),
            authority=dict(_AUTHORITY), budget_status=deepcopy(route["budget_status"]),
            consistency_scope=cached._SCOPE))
    except (routing.RoutingError, cached.IRCellRuntimeError) as error:
        raise OriginalCorpusRuntimeError(str(error)) from error
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise OriginalCorpusRuntimeError("invalid original corpus replay binding") from error


class _OriginalCorpusAutoencoder:
    def __init__(self, owner, options, plan):
        self._owner = owner
        self._options_bytes, self._plan_bytes = cached._raw(options), cached._raw(plan)
        self._inferred = False

    def _recheck(self):
        import json
        options = json.loads(self._options_bytes)
        plan = prepare_ir_original_corpus_runtime(**options)
        _require(cached._raw(plan) == self._plan_bytes, "original corpus binding changed since opening")
        return plan

    def describe(self):
        import json
        plan = json.loads(self._plan_bytes)
        return deepcopy(dict(schema="ir-original-corpus-runtime-description/v1",
            runtime_selection=dict(request=plan["route"]["request"], runtime_id=plan["package_manifest"]["runtime"],
                checkpoint=plan["route"]["selected_checkpoint"]["receipt"], package_manifest=plan["package_manifest_receipt"]),
            row_selection=dict(corpus_receipt=plan["corpus_receipt"], split=plan["corpus_split"], row_ids=plan["row_ids"]),
            original_corpus_membership=plan["original_corpus_membership"], capability=plan["capability"],
            model_load_performed=True, cached_inference_executed=self._inferred,
            authority=dict(_AUTHORITY), budget_status=plan["budget_status"], consistency_scope=cached._SCOPE))

    def infer_cached(self):
        """Run only the fixed original target-free rows; accept no new inputs/options."""
        plan = self._recheck()
        rows = deepcopy(plan["inputs"])
        before = cached._raw(rows)
        result = self._owner.infer(rows)
        self._inferred = True
        _require(cached._raw(rows) == before, "runtime mutated original corpus call inputs")
        self._recheck()
        return deepcopy(dict(schema="ir-original-corpus-inference/v1", runtime_selection=self.describe()["runtime_selection"],
            row_receipts=plan["row_receipts"], raw_candidate_report=result, model_inference_executed=True,
            authority=dict(_AUTHORITY), budget_status=plan["budget_status"], consistency_scope=cached._SCOPE))


def _open_ir_original_corpus_autoencoder(directory_plan_pin, inventory_pins, request, *,
        package_manifest_pin, corpus_pin, corpus_split, row_ids, max_reference_bytes=MAX_REFERENCE_BYTES):
    try:
        options = _options(directory_plan_pin, inventory_pins, request, package_manifest_pin,
                           corpus_pin, corpus_split, row_ids, max_reference_bytes)
        plan = prepare_ir_original_corpus_runtime(**deepcopy(options))
        paths = {name: Path(pin["path"]) for name, pin in plan["package_file_receipts"].items()}
        owner = hub._instantiate(deepcopy(plan["package_manifest"]), paths)
        wrapped = _OriginalCorpusAutoencoder(owner, options, plan)
        wrapped._recheck()
        return wrapped
    except (routing.RoutingError, cached.IRCellRuntimeError) as error:
        raise OriginalCorpusRuntimeError(str(error)) from error


__all__ = ["SCHEMA", "OriginalCorpusRuntimeError", "prepare_ir_original_corpus_runtime"]
