"""Bounded original-bound catalog continuation over the existing public scorer.

No numerical primitive, parser, model session, optimizer or source encoder is
introduced. Recorded lineage and caller declarations confer no proof authority.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct

SCHEMA = "legal-compact-catalog-trained-generation/v1"
PROFILE = "bounded-trained-catalog-generation-384/v1"
VALIDATION_SCHEMA = "legal-compact-catalog-trained-generation-validation/v1"
VALIDATION_PROFILE = "original-bound-catalog-generation-replay/v1"
BATCH_SCHEMA = "legal-compact-catalog-trained-batch-prediction/v1"
BATCH_PROFILE = "verified-catalog-trace-to-declared-observation/v1"
PREDICTIONS_SCHEMA = "legal-relational-catalog-token-batch-predictions/v1"
MAX_NEW_TOKENS, MAX_SEQUENCE_TOKENS = 12, 512
MAX_CHECKPOINT_BYTES, MAX_INPUT_BYTES = 64 * 1024**2, 96 * 1024**2
MAX_REPORT_BYTES = MAX_TRACE_BYTES = 8 * 1024**2
MAX_SCORE_BYTES, MAX_CONTEXT_BYTES, MAX_CODEC_BYTES = 4 * 1024**2, 524288, 32768
MAX_POPULATION_BYTES, MAX_POPULATION_ROWS = 128 * 1024, 64
MAX_SOURCE_BYTES, MAX_JSON_ITEMS, MAX_JSON_DEPTH = 4 * 1024**2, 12_000_000, 96
PREFIX_ORIGINS = ("bos_seed", "authored_fixture", "target_derived_label", "caller_supplied_unverified")
CATALOG_CONTEXT_ORIGINS = ("authored_fixture", "target_derived_label", "caller_supplied_unverified")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SCORER_MODULE = "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_catalog_trained_scoring_v1"
_SOURCE_SPECS = (
    ("logic/formalization/autoencoder/legal_compact_catalog_trained_scoring_v1.py", "34a498e0f409a205913efa0e6661e66c8dbb848da11845a68afda7836d191e9f"),
    ("logic/autoformal/legal_relational_batch_core_v1.py", "bbf3828ff6637e7848e7c6b689d07ae8d4825f7842472cc61ef516e79d8ca97c"),
    ("logic/autoformal/legal_relational_catalog_batch_evaluation_v1.py", "96c951967f00eb202c3fc1340e29d034f7184cfeca85dcef20fb3622aeea52e6"),
)
_AUTHORITY = dict.fromkeys(("catalog_training_verified", "training_history_authenticated",
    "source_semantics_verified", "source_bound", "source_encoder_authenticated", "conditioning_producer_verified",
    "context_permission_verified", "permitted_inference_context_verified", "prefix_origin_verified",
    "prefix_independence_verified", "held_out_generation_verified", "training_qualified", "evaluation_gold_qualified",
    "legal_accuracy_established", "statutory_accuracy_verified", "accepted", "admitted", "proof_authority", "Lean_admitted"), False)
_META_FIELDS = ("weights_sha256", "training_checkpoint_profile", "training_codec", "training_codec_sha256",
    "inference_codec", "inference_codec_sha256", "bridge", "bridge_sha256", "lexical_bridge_verified",
    "numeric_conditioning", "declared_runtime", "compact_training_steps", "training_progress",
    "initial_checkpoint_sha256", "initial_weights_sha256", "parent_checkpoint_sha256", "optimizer_state_sha256",
    "optimizer_config", "optimizer_policy", "training_population_sha256", "training_population_count")
_LIMITATIONS = [
    "The complete original training codec and distinct catalog inference policy remain separately identified; no checkpoint is relabeled as catalog-trained.",
    "Supplied prefix IDs remain separate from emitted IDs. Forced tokens and complete supplied prefixes do not establish learned complete reconstruction.",
    "Every actual score consumes the whole current prefix through the unchanged public scorer. No prepared session or cross-call numeric cache is used.",
    "Caller conditioning, prefix origins and catalog origins are declarations; no source encoder, permitted inference context, historical training or legal interpretation is authenticated.",
    "Original generation counts describe this generation; validation and adaptation return explicit replay receipts. Referenced historical counts must not be added to this-call counters.",
    "A failed call returns no successful partial trace; absence of a result does not establish zero attempted numerical work. The enclosing admitted ledger must retain failures and actual work evidence.",
    "Complete bounded output is required; source/input endpoint fences do not establish arbitrary bytecode attestation or operating-system containment.",
]

class CompactCatalogTrainedGenerationError(ValueError):
    """Closed-input, custody, trace or original-bound replay refusal."""

_SCORE_FIELDS = {
    'actual_runtime', 'authority', 'bridge', 'bridge_sha256', 'catalog_context_raw_sha256',
    'catalog_context_raw_utf8', 'catalog_sha256', 'catalog_training_verified', 'checkpoint_sha256',
    'compact_training_steps', 'conditioning', 'conditioning_sha256', 'context_sha256', 'declared_runtime',
    'evaluation_gold_mask', 'inference_codec', 'inference_codec_sha256', 'initial_checkpoint_sha256',
    'initial_weights_sha256', 'lexical_bridge_verified', 'limitations', 'logits', 'logits_sha256',
    'model_executed', 'model_restore_performed', 'next_prefix_ids', 'numeric_conditioning',
    'numerical_forward_count', 'numerical_forward_executed', 'optimizer_config', 'optimizer_constructed',
    'optimizer_executed', 'optimizer_policy', 'optimizer_state_restored', 'optimizer_state_sha256',
    'original_forward_count', 'output_shape', 'owner_pins', 'parent_checkpoint_sha256', 'prefix_ids',
    'prefix_report', 'profile', 'reason', 'reference_forward_count', 'replay_forward_count',
    'runtime_torch_version_verified', 'runtime_verified', 'schema', 'selection', 'status',
    'training_checkpoint_profile', 'training_codec', 'training_codec_sha256', 'training_executed',
    'training_mask', 'training_population_count', 'training_population_sha256', 'training_progress',
    'weights_sha256',
}

def _need(value, message):
    if not value:
        raise CompactCatalogTrainedGenerationError(message)

def _copy(value, maximum, *, allow_bytes=False):
    remaining, items, active = maximum, MAX_JSON_ITEMS, set()

    def charge(count):
        nonlocal remaining
        remaining -= count
        _need(remaining >= 0, "whole ordinary byte bound exceeded")

    def visit(item, depth):
        nonlocal items
        items -= 1
        _need(items >= 0 and depth <= MAX_JSON_DEPTH, "whole ordinary item/depth bound exceeded")
        if type(item) in (dict, list):
            _need(id(item) not in active and len(item) <= items, "cyclic or oversized ordinary container")
            active.add(id(item))
            charge(2)
            try:
                if type(item) is dict:
                    result = {}
                    for index, (key, child) in enumerate(item.items()):
                        _need(type(key) is str, "plain string keys required")
                        charge(1 + bool(index))
                        result[visit(key, depth + 1)] = visit(child, depth + 1)
                    return result
                result = []
                for index, child in enumerate(item):
                    charge(bool(index))
                    result.append(visit(child, depth + 1))
                return result
            finally:
                active.remove(id(item))
        if type(item) is bytes and allow_bytes:
            charge(len(item))
        elif type(item) is str:
            _need(len(item) <= maximum, "bounded string required")
            charge(2)
            for character in item:
                code = ord(character)
                _need(code != 0 and not 0xD800 <= code <= 0xDFFF, "ordinary scalar UTF8 required")
                charge(2 if character in ('"', "\\") or character in "\b\f\n\r\t"
                       else 6 if code < 32 else 1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
        elif item is None or type(item) is bool:
            charge(4 if item is None or item is True else 5)
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded exact integer required")
            charge(len(str(item)))
        elif type(item) is float:
            _need(math.isfinite(item), "finite plain scalar required")
            charge(len(repr(item)))
        else:
            raise CompactCatalogTrainedGenerationError("ordinary JSON containers/primitives required")
        return item

    try:
        return visit(value, 0)
    except (RuntimeError, RecursionError) as error:
        raise CompactCatalogTrainedGenerationError("stable bounded ordinary inputs required") from error

def _wire(value, maximum=MAX_REPORT_BYTES):
    raw = json.dumps(_copy(value, maximum), sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(len(raw) <= maximum, "complete serialized byte bound exceeded; truncation refused")
    return raw

def _digest(value, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()

def _fingerprint(value):
    digest = hashlib.sha256()

    def visit(item):
        if type(item) is dict:
            digest.update(b"d" + str(len(item)).encode() + b":")
            for key in sorted(item):
                visit(key)
                visit(item[key])
        elif type(item) is list:
            digest.update(b"l" + str(len(item)).encode() + b":")
            for child in item:
                visit(child)
        elif type(item) is bytes:
            digest.update(b"b" + str(len(item)).encode() + b":" + item)
        else:
            digest.update(b"j" + _wire(item, MAX_INPUT_BYTES))
    visit(value)
    return digest.hexdigest()

def _snapshot(path):
    _need(path.is_absolute() and all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents),
          "unaliased canonical source parents required")
    identity = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_size,
                            row.st_mtime_ns, row.st_ctime_ns, row.st_nlink)
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_SOURCE_BYTES,
          "bounded single-link source required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        _need(identity(os.fstat(source.fileno())) == identity(before), "source changed before open")
        raw = source.read(before.st_size + 1)
        after = os.fstat(source.fileno())
    _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat()),
          "source identity changed during read")
    return hashlib.sha256(raw).hexdigest(), identity(after)

_SELF_SNAPSHOT = _snapshot(_SELF_PATH)


def _sources():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SOURCE_SPECS[0][0]).is_file():
                _need(candidate.resolve() == candidate, "canonical dependency root required")
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "fixed catalog scorer unavailable")
    snapshots = {str(_SELF_PATH): _snapshot(_SELF_PATH)}
    _need(snapshots[str(_SELF_PATH)] == _SELF_SNAPSHOT, "generation owner changed since import")
    for relative, expected in _SOURCE_SPECS:
        path = root / relative
        snapshots[str(path)] = _snapshot(path)
        _need(snapshots[str(path)][0] == expected, "fixed generation dependency differs")
    return root, snapshots


def _closing(loaded):
    root, snapshots, modules = loaded
    current_root, direct = _sources()
    _need(current_root == root and all(snapshots.get(path) == value for path, value in direct.items()),
          "generation physical source custody changed")
    scorer = modules["scorer"]
    path = root / _SOURCE_SPECS[0][0]
    _need(type(scorer.__file__) is str and Path(scorer.__file__).absolute() == path
          and scorer._SELF_SNAPSHOT == snapshots[str(path)], "scoring import anchor changed")
    scorer._closing(modules["scorer_loaded"])
    _need(modules["scorer_loaded"][0] == root
          and {**modules["scorer_loaded"][1], **direct} == snapshots,
          "complete inherited scoring source closure differs")
    _need(modules["catalog"] is modules["scorer_loaded"][2]["catalog"], "catalog owner changed")


def _owners():
    root, direct = _sources()
    failure = None
    try:
        scorer = importlib.import_module(_SCORER_MODULE)
        path = root / _SOURCE_SPECS[0][0]
        _need(type(scorer.__file__) is str and Path(scorer.__file__).absolute() == path
              and scorer._SELF_SNAPSHOT == direct[str(path)], "fixed scoring owner origin differs")
        nested = scorer._owners()
        _need(nested[0] == root, "scoring dependency root differs")
        for name in set(direct) & set(nested[1]):
            _need(direct[name] == nested[1][name], "shared source identity differs")
        loaded = (root, {**nested[1], **direct},
                  {"scorer": scorer, "catalog": nested[2]["catalog"], "scorer_loaded": nested})
        _closing(loaded)
        return loaded
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _need(_sources() == (root, direct), "source changed during generation imports")
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing generation lazy-import fence also failed.")


def _pins(loaded):
    return [{"path": name, "bytes": value[1][3], "sha256": value[0]}
            for name, value in sorted(loaded[1].items())]


def _operation(original, work, preflight=None):
    snapshot = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    token = _fingerprint(snapshot)
    loaded, failure, retained = None, None, []

    def fence():
        _need(_fingerprint(_copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
              and _fingerprint(snapshot) == token, "original or captured generation inputs changed")
        if loaded is not None:
            _closing(loaded)
        for value, maximum, digest in retained:
            _need(_digest(value, maximum) == digest, "retained generation observation changed")

    def keep(value, maximum=MAX_REPORT_BYTES):
        retained.append((value, maximum, _digest(value, maximum)))
        return value

    def call(function, *args, **kwargs):
        arguments = dict(args=list(args), kwargs=kwargs)
        captured = _fingerprint(_copy(arguments, MAX_INPUT_BYTES, allow_bytes=True))
        fence()
        primary = None
        try:
            return function(*args, **kwargs)
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                _need(_fingerprint(_copy(arguments, MAX_INPUT_BYTES, allow_bytes=True)) == captured,
                      "cross-owner generation inputs changed")
                fence()
            except BaseException:
                if primary is None:
                    raise
                BaseException.add_note(primary, "A closing cross-owner generation fence also failed.")

    try:
        if preflight is not None:
            preflight(snapshot)
        fence()
        loaded = _owners()
        result = work(snapshot, loaded, fence, keep, call)
        raw = _wire(result)
        fence()
        return json.loads(raw)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing generation input/source custody check also failed.")


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, "independent lowercase SHA256 required: " + label)


def _input_preflight(data):
    _hash(data["expected_checkpoint_sha256"], "checkpoint")
    _hash(data["expected_catalog_context_sha256"], "catalog context")
    _need(type(data["checkpoint"]) is dict
          and _digest(data["checkpoint"], MAX_CHECKPOINT_BYTES) == data["expected_checkpoint_sha256"],
          "complete original checkpoint commitment differs")
    vector, prefix, raw = data["conditioning"], data["prefix_ids"], data["catalog_context_raw"]
    _need(type(vector) is list and len(vector) == 384
          and all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 1e8 for x in vector),
          "bounded plain 384-value conditioning required")
    _need(type(prefix) is list and 1 <= len(prefix) <= MAX_SEQUENCE_TOKENS
          and all(type(x) is int for x in prefix), "nonempty bounded plain integer prefix required")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_CONTEXT_BYTES
          and hashlib.sha256(raw).hexdigest() == data["expected_catalog_context_sha256"],
          "complete original catalog context commitment differs")
    _need(type(data["max_new_tokens"]) is int and 1 <= data["max_new_tokens"] <= MAX_NEW_TOKENS,
          "max_new_tokens must be an exact integer in 1..12")
    _need(type(data["prefix_origin"]) is str and data["prefix_origin"] in PREFIX_ORIGINS
          and (data["prefix_origin"] != "bos_seed" or prefix == [1]), "declared prefix origin differs")
    _need(type(data["catalog_context_origin"]) is str and data["catalog_context_origin"] in CATALOG_CONTEXT_ORIGINS,
          "declared catalog context origin differs")


def _inputs(checkpoint, conditioning, prefix_ids, catalog_context_raw, expected_checkpoint_sha256,
            expected_catalog_context_sha256, max_new_tokens, prefix_origin, catalog_context_origin):
    return dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids,
        catalog_context_raw=catalog_context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_catalog_context_sha256=expected_catalog_context_sha256, max_new_tokens=max_new_tokens,
        prefix_origin=prefix_origin, catalog_context_origin=catalog_context_origin)


def _kwargs(data):
    return {name: data[name] for name in ("expected_checkpoint_sha256", "expected_catalog_context_sha256",
                                        "max_new_tokens", "prefix_origin", "catalog_context_origin")}


def _authority(report, expected=_AUTHORITY):
    _need(type(report["authority"]) is dict and set(report["authority"]) == set(expected)
          and all(value is False for value in report["authority"].values())
          and type(report["training_mask"]) is int and report["training_mask"] == 0
          and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0,
          "authority or exact integer masks differ")


def _prefix(report, current, data, codec_sha, loaded):
    scorer = loaded[2]["scorer"]
    return scorer._prefix_report(report, {**data, "prefix_ids": current}, codec_sha, loaded[2]["scorer_loaded"])


def _score(offered, current, data, loaded):
    score = _copy(offered, MAX_SCORE_BYTES)
    scorer, catalog, nested = (loaded[2][name] for name in ("scorer", "catalog", "scorer_loaded"))
    _need(type(score) is dict and set(score) == _SCORE_FIELDS and score["schema"] == scorer.SCHEMA
          and score["profile"] == scorer.PROFILE, "complete unchanged scoring receipt required")
    _authority(score, scorer._AUTHORITY)
    _need(_wire(score["owner_pins"]) == _wire(scorer._pins(nested)), "complete scoring source inventory differs")
    checkpoint = data["checkpoint"]
    _need(score["checkpoint_sha256"] == data["expected_checkpoint_sha256"]
          and score["weights_sha256"] == checkpoint["weights_sha256"]
          and _wire(score["conditioning"]) == _wire(data["conditioning"])
          and score["conditioning_sha256"] == _digest(data["conditioning"])
          and _wire(score["prefix_ids"]) == _wire(current)
          and score["catalog_context_raw_utf8"].encode("utf-8") == data["catalog_context_raw"]
          and score["catalog_context_raw_sha256"] == data["expected_catalog_context_sha256"],
          "scoring original input commitments differ")
    training, training_sha, inference_sha, bridge = scorer._bridge(checkpoint, score["inference_codec"], catalog)
    _need(_wire(score["training_codec"], MAX_CODEC_BYTES) == _wire(training, MAX_CODEC_BYTES)
          and score["training_codec_sha256"] == training_sha and score["inference_codec_sha256"] == inference_sha
          and _wire(score["bridge"], MAX_CODEC_BYTES) == _wire(bridge, MAX_CODEC_BYTES)
          and score["bridge_sha256"] == _digest(bridge, MAX_CODEC_BYTES)
          and score["lexical_bridge_verified"] is True, "complete codec bridge differs")
    lineage = {"training_checkpoint_profile": checkpoint["profile"], "training_progress": checkpoint["progress"],
        "compact_training_steps": checkpoint["progress"]["optimizer_steps"],
        "initial_checkpoint_sha256": checkpoint["initial_checkpoint_sha256"], "initial_weights_sha256": checkpoint["initial_weights_sha256"],
        "parent_checkpoint_sha256": checkpoint["parent_checkpoint_sha256"], "optimizer_config": checkpoint["optimizer_config"],
        "optimizer_policy": checkpoint["optimizer_policy"], "optimizer_state_sha256": _digest(checkpoint["optimizer_state"], MAX_CHECKPOINT_BYTES),
        "training_population_sha256": checkpoint["population_sha256"], "training_population_count": checkpoint["population_count"],
        "declared_runtime": checkpoint["runtime"]}
    _need(all(_wire(score[name]) == _wire(value) for name, value in lineage.items()), "original trained metadata differs")
    _need(all(score[name] is False for name in ("training_executed", "optimizer_executed", "optimizer_constructed",
          "optimizer_state_restored", "catalog_training_verified")), "scoring training boundary differs")
    numeric = [struct.unpack("!f", struct.pack("!f", float(x)))[0] for x in data["conditioning"]]
    _need(_wire(score["numeric_conditioning"]) == _wire(numeric), "original numerical conditioning differs")
    prefix = _prefix(score["prefix_report"], current, data, inference_sha, loaded)
    _need(score["context_sha256"] == prefix["context_sha256"] and score["catalog_sha256"] == prefix["catalog_sha256"],
          "scoring complete catalog commitment differs")
    active = bool(prefix["allowed_token_ids"])
    for name in ("numerical_forward_executed", "model_restore_performed", "model_executed", "runtime_verified", "runtime_torch_version_verified"):
        _need(score[name] is active, "scoring numerical/runtime flags differ")
    for name, expected in (("numerical_forward_count", int(active)), ("original_forward_count", int(active)),
                           ("replay_forward_count", 0), ("reference_forward_count", 0)):
        _need(type(score[name]) is int and score[name] == expected, "scoring execution count differs")
    if active:
        logits = score["logits"]
        _need(score["status"] == "scored" and score["reason"] is None
              and type(logits) is list and len(logits) == 537
              and all(type(value) is float and math.isfinite(value) for value in logits)
              and score["logits_sha256"] == _digest(logits, 32768)
              and _wire(score["output_shape"]) == _wire([1, len(current), 537])
              and _wire(score["actual_runtime"]) == _wire(checkpoint["runtime"]), "actual full numerical observation differs")
        selection = scorer._selection_report(score["selection"], logits, prefix,
            {**data, "prefix_ids": current}, inference_sha, nested)
        _need(_wire(score["next_prefix_ids"]) == _wire(selection["next_prefix_ids"]), "selected prefix extension differs")
    else:
        _need(score["status"] == "no_forward" and score["reason"] == (prefix["reason"] or prefix["status"])
              and all(score[name] is None for name in ("logits", "logits_sha256", "selection", "output_shape", "actual_runtime"))
              and _wire(score["next_prefix_ids"]) == _wire(current), "zero-forward receipt differs")
    _need(_wire(score["limitations"]) == _wire(scorer._LIMITATIONS), "complete scoring limitations differ")
    return score


def _decoded(offered, current, prefix, data, codec_sha, loaded):
    value = _copy(offered, 2 * 1024**2)
    catalog, scorer = loaded[2]["catalog"], loaded[2]["scorer"]
    fields = {"schema", "profile", "format", "selection_policy", "codec_sha256", "context_sha256", "context_raw_sha256",
        "catalog_context", "catalog_sha256", "owner_pins", "authority", "training_mask", "evaluation_gold_mask",
        "status", "reason", "generated_ids", "generated_content_raw_utf8", "generated_content_hex",
        "generated_content_sha256", "framing", "selection", "counts"}
    _need(type(value) is dict and set(value) == fields and value["schema"] == catalog.CANDIDATE_SCHEMA
          and value["profile"] == catalog.PROFILE and value["format"] == catalog.FORMAT
          and value["selection_policy"] == catalog.SELECTION_POLICY
          and _wire(value["generated_ids"]) == _wire(current) and value["codec_sha256"] == codec_sha
          and value["context_raw_sha256"] == data["expected_catalog_context_sha256"]
          and value["context_sha256"] == prefix["context_sha256"] and value["catalog_sha256"] == prefix["catalog_sha256"]
          and _wire(value["catalog_context"]) == _wire(prefix["catalog_context"]), "final original catalog intake differs")
    _authority(value, catalog._AUTHORITY)
    scorer._producer_rows(value, loaded[2]["scorer_loaded"],
        ["logic/formalization/autoencoder/legal_compact_catalog_tokens_v1.py", *[relative for relative, _ in catalog._SOURCE_SPECS]])
    if prefix["status"] == "complete":
        _need(value["status"] == "valid_candidate" and value["reason"] is None
              and type(value["selection"]) is dict and _wire(value["counts"]) == _wire(prefix["counts"]),
              "complete prefix and public candidate disagree")
    else:
        expected_status = "incomplete" if prefix["status"] == "prefix" else "rejected"
        expected_reason = "missing_eos" if expected_status == "incomplete" else prefix["reason"]
        if current[-1] == 2 and expected_reason == "invalid_compact_prefix":
            expected_reason = "invalid_compact_content"
        _need(value["status"] == expected_status and value["reason"] == expected_reason
              and value["selection"] is None and value["counts"] is None, "noncomplete public candidate differs")
    return value


def _disposition(prefix, emitted):
    if prefix["status"] == "complete":
        return ("complete", None) if emitted else ("supplied_complete", "supplied_prefix_already_complete")
    if prefix["status"] == "budget_exhausted":
        return "token_budget_exhausted", prefix["reason"]
    return "blocked", prefix["reason"] or prefix["status"]


def generate_compact_catalog_trained_v1(checkpoint, conditioning, prefix_ids, catalog_context_raw, *,
        expected_checkpoint_sha256, expected_catalog_context_sha256, max_new_tokens, prefix_origin, catalog_context_origin):
    """Retain at most twelve actual public-scorer steps and complete final intake."""
    original = _inputs(checkpoint, conditioning, prefix_ids, catalog_context_raw, expected_checkpoint_sha256,
        expected_catalog_context_sha256, max_new_tokens, prefix_origin, catalog_context_origin)

    def work(data, loaded, fence, keep, call):
        scorer, catalog = loaded[2]["scorer"], loaded[2]["catalog"]
        trace, emitted, argmax = [], [], []
        current, final_prefix = list(data["prefix_ids"]), None
        trace_bytes = 2
        settings = dict(max_new_tokens=data["max_new_tokens"], max_total_ids=MAX_SEQUENCE_TOKENS,
                        prefix_origin=data["prefix_origin"], catalog_context_origin=data["catalog_context_origin"])
        while True:
            offered = call(scorer.score_compact_catalog_trained_v1, data["checkpoint"], data["conditioning"], current,
                data["catalog_context_raw"], expected_checkpoint_sha256=data["expected_checkpoint_sha256"],
                expected_catalog_context_sha256=data["expected_catalog_context_sha256"])
            score = keep(_score(offered, current, data, loaded), MAX_SCORE_BYTES)
            fence()
            trace_bytes += len(_wire(score, MAX_SCORE_BYTES)) + bool(trace)
            _need(trace_bytes <= MAX_TRACE_BYTES, "whole trace byte bound exceeded; no partial trace returned")
            trace.append(score)
            if len(trace) > 1:
                _need(all(_wire(score[name]) == _wire(trace[0][name]) for name in _META_FIELDS),
                      "fixed checkpoint/codec metadata changed between steps")
            final_prefix = score["prefix_report"]
            if score["status"] == "no_forward":
                status, reason = _disposition(final_prefix, emitted)
                break
            selected = score["selection"]
            emitted.append(selected["selected_token_id"])
            argmax.append(selected["raw_argmax_token_id"])
            current = list(score["next_prefix_ids"])
            options = dict(expected_context_sha256=data["expected_catalog_context_sha256"],
                codec=score["inference_codec"], expected_codec_sha256=score["inference_codec_sha256"])
            offered_prefix = call(catalog.compact_catalog_allowed_token_ids_v1, current, data["catalog_context_raw"], **options)
            final_prefix = keep(_prefix(offered_prefix, current, data, score["inference_codec_sha256"], loaded), 2 * 1024**2)
            fence()
            if not final_prefix["allowed_token_ids"]:
                status, reason = _disposition(final_prefix, emitted)
                break
            if len(emitted) == data["max_new_tokens"]:
                status, reason = "step_budget_exhausted", "max_new_tokens_reached"
                break
        first = trace[0]
        options = dict(expected_context_sha256=data["expected_catalog_context_sha256"],
            codec=first["inference_codec"], expected_codec_sha256=first["inference_codec_sha256"])
        raw_decoding = call(catalog.decode_compact_catalog_tokens_v1, current, data["catalog_context_raw"], **options)
        decoded = keep(_decoded(raw_decoding, current, final_prefix, data, first["inference_codec_sha256"], loaded), 2 * 1024**2)
        exposure = dict(teacher_forcing=data["prefix_ids"] != [1],
            target_access=data["prefix_origin"] == "target_derived_label" or data["catalog_context_origin"] == "target_derived_label",
            encoder_sha256=None, source_encoder_authenticated=False, context_permission_verified=False, prefix_origin_verified=False)
        result = {name: first[name] for name in _META_FIELDS}
        result.update(schema=SCHEMA, profile=PROFILE, status=status, reason=reason,
            checkpoint_sha256=data["expected_checkpoint_sha256"], conditioning=data["conditioning"],
            conditioning_sha256=_digest(data["conditioning"]), initial_prefix_ids=data["prefix_ids"],
            prefix_origin=data["prefix_origin"], catalog_context_origin=data["catalog_context_origin"],
            catalog_context_raw_utf8=data["catalog_context_raw"].decode("utf-8"),
            catalog_context_raw_sha256=data["expected_catalog_context_sha256"],
            context_sha256=decoded["context_sha256"], catalog_sha256=decoded["catalog_sha256"],
            settings=settings, settings_sha256=_digest(settings), trace=trace, selected_token_ids=emitted,
            raw_argmax_ids_by_step=argmax, generated_ids=current, emitted_token_count=len(emitted), total_token_count=len(current),
            score_call_count=len(trace), numerical_forward_count=len(emitted), original_forward_count=len(emitted),
            replay_forward_count=0, reference_forward_count=0, final_prefix_report=final_prefix, final_decoding=decoded,
            exposure=exposure, actual_runtime=first["actual_runtime"] if emitted else None,
            model_executed=bool(emitted), runtime_verified=bool(emitted), runtime_torch_version_verified=bool(emitted),
            training_executed=False, optimizer_executed=False, optimizer_constructed=False, optimizer_state_restored=False,
            catalog_training_verified=False, owner_pins=_pins(loaded), authority=dict(_AUTHORITY),
            training_mask=0, evaluation_gold_mask=0, limitations=list(_LIMITATIONS))
        fence()
        return result
    return _operation(original, work, _input_preflight)


_REPORT_FIELDS = set(_META_FIELDS) | {"schema", "profile", "status", "reason", "checkpoint_sha256", "conditioning",
    "conditioning_sha256", "initial_prefix_ids", "prefix_origin", "catalog_context_origin", "catalog_context_raw_utf8",
    "catalog_context_raw_sha256", "context_sha256", "catalog_sha256", "settings", "settings_sha256", "trace",
    "selected_token_ids", "raw_argmax_ids_by_step", "generated_ids", "emitted_token_count", "total_token_count",
    "score_call_count", "numerical_forward_count", "original_forward_count", "replay_forward_count", "reference_forward_count",
    "final_prefix_report", "final_decoding", "exposure", "actual_runtime", "model_executed", "runtime_verified",
    "runtime_torch_version_verified", "training_executed", "optimizer_executed", "optimizer_constructed", "optimizer_state_restored",
    "catalog_training_verified", "owner_pins", "authority", "training_mask", "evaluation_gold_mask", "limitations"}


def _report(value):
    checked = _copy(value, MAX_REPORT_BYTES)
    _need(type(checked) is dict and set(checked) == _REPORT_FIELDS and checked["schema"] == SCHEMA
          and checked["profile"] == PROFILE, "complete closed generation report required")
    _authority(checked)
    return checked


def compact_catalog_trained_generation_sha256(report):
    """Hash a closed whole report; this performs no numerical validation replay."""
    def work(data, loaded, fence, keep, call):
        return _digest(_report(data["report"]))
    return _operation(dict(report=report), work, lambda data: _report(data["report"]))


def _replay_preflight(data):
    _input_preflight(data)
    _hash(data["expected_report_sha256"], "generation report")
    _need(_digest(_report(data["report"])) == data["expected_report_sha256"], "independent generation report pin differs")


def _replay_accounting(count):
    return dict(original_generation_forward_count=count, numerical_replay_forward_count=count,
        numerical_forward_count=count, original_forward_count=0, replay_forward_count=count,
        reference_forward_count=0, count_categories_overlap=True, model_executed=bool(count), runtime_verified=bool(count),
        training_executed=False, optimizer_executed=False, optimizer_constructed=False, optimizer_state_restored=False)


def validate_compact_catalog_trained_generation_v1(report, checkpoint, conditioning, prefix_ids, catalog_context_raw, *,
        expected_report_sha256, expected_checkpoint_sha256, expected_catalog_context_sha256,
        max_new_tokens, prefix_origin, catalog_context_origin):
    """Replay all original inputs and return explicit this-call replay accounting."""
    original = _inputs(checkpoint, conditioning, prefix_ids, catalog_context_raw, expected_checkpoint_sha256,
        expected_catalog_context_sha256, max_new_tokens, prefix_origin, catalog_context_origin)
    original.update(report=report, expected_report_sha256=expected_report_sha256)

    def work(data, loaded, fence, keep, call):
        regenerated = keep(call(generate_compact_catalog_trained_v1, data["checkpoint"], data["conditioning"],
            data["prefix_ids"], data["catalog_context_raw"], **_kwargs(data)))
        _need(_wire(regenerated) == _wire(data["report"]), "generation differs from complete original-bound replay")
        count = regenerated["numerical_forward_count"]
        result = dict(schema=VALIDATION_SCHEMA, profile=VALIDATION_PROFILE,
            generation_report=regenerated, generation_sha256=data["expected_report_sha256"], generation_regenerated=True,
            checkpoint_sha256=data["expected_checkpoint_sha256"], catalog_context_raw_sha256=data["expected_catalog_context_sha256"],
            settings_sha256=regenerated["settings_sha256"], owner_pins=_pins(loaded), authority=dict(_AUTHORITY),
            training_mask=0, evaluation_gold_mask=0,
            limitations=["The nested report describes the original trajectory byte-for-byte. Its original counters are historical references during this replay.",
                "This receipt's numerical_forward_count and numerical_replay_forward_count refer to the same replay and must not be summed.",
                "Original-bound numerical replay grants no encoder, catalog permission, legal meaning, training or proof authority."])
        result.update(_replay_accounting(count))
        fence()
        return result
    return _operation(original, work, _replay_preflight)


def _population(raw, expected):
    _hash(expected, "whole population")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_POPULATION_BYTES and hashlib.sha256(raw).hexdigest() == expected,
          "complete original population commitment differs")

    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result, "duplicate population JSON field")
            result[key] = value
        return result

    value = _copy(json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(CompactCatalogTrainedGenerationError("finite population JSON required"))), MAX_POPULATION_BYTES)
    _need(type(value) is dict and set(value) == {"schema", "partition", "selection_sha256", "rows"}
          and value["schema"] == "legal-relational-batch-population/v1"
          and type(value["partition"]) is str and 0 < len(value["partition"]) <= 128 and bool(value["partition"].strip())
          and type(value["rows"]) is list and 1 <= len(value["rows"]) <= MAX_POPULATION_ROWS,
          "complete closed bounded population required")
    _hash(value["selection_sha256"], "population selection")
    seen = set()
    for row in value["rows"]:
        _need(type(row) is dict and set(row) == {"id", "source_sha256", "context_sha256"}
              and type(row["id"]) is str and 0 < len(row["id"]) <= 256 and bool(row["id"].strip())
              and row["id"] not in seen, "complete unique population occurrences required")
        seen.add(row["id"])
        _hash(row["source_sha256"], "population source")
        _hash(row["context_sha256"], "selected source-context")
    return value


def prepare_compact_catalog_trained_batch_prediction_v1(report, checkpoint, conditioning, prefix_ids, catalog_context_raw,
        population_raw, *, expected_generation_sha256, expected_population_sha256, occurrence_id,
        expected_checkpoint_sha256, expected_catalog_context_sha256, max_new_tokens, prefix_origin, catalog_context_origin):
    """Numerically replay one trajectory and bind it to the unchanged whole population."""
    original = _inputs(checkpoint, conditioning, prefix_ids, catalog_context_raw, expected_checkpoint_sha256,
        expected_catalog_context_sha256, max_new_tokens, prefix_origin, catalog_context_origin)
    original.update(report=report, expected_report_sha256=expected_generation_sha256,
        population_raw=population_raw, expected_population_sha256=expected_population_sha256, occurrence_id=occurrence_id)

    def preflight(data):
        _replay_preflight(data)
        population = _population(data["population_raw"], data["expected_population_sha256"])
        _need(type(data["occurrence_id"]) is str and any(row["id"] == data["occurrence_id"] for row in population["rows"]),
              "one declared population occurrence required")

    def work(data, loaded, fence, keep, call):
        population = keep(_population(data["population_raw"], data["expected_population_sha256"]), MAX_POPULATION_BYTES)
        validation = keep(call(validate_compact_catalog_trained_generation_v1, data["report"], data["checkpoint"],
            data["conditioning"], data["prefix_ids"], data["catalog_context_raw"],
            expected_report_sha256=data["expected_report_sha256"], **_kwargs(data)))
        value = validation["generation_report"]
        _need(validation["schema"] == VALIDATION_SCHEMA and validation["profile"] == VALIDATION_PROFILE
              and validation["generation_sha256"] == data["expected_report_sha256"]
              and validation["generation_regenerated"] is True
              and _wire(value) == _wire(data["report"]), "public replay receipt disagrees with original generation")
        _authority(validation)
        count = value["numerical_forward_count"]
        _need(all(_wire(validation[name]) == _wire(expected) for name, expected in _replay_accounting(count).items()),
              "public replay accounting differs")
        source_row = next(row for row in population["rows"] if row["id"] == data["occurrence_id"])
        exposure = value["exposure"]
        observation = {**source_row, "status": "generated", "teacher_forcing": exposure["teacher_forcing"],
            "target_access": exposure["target_access"], "generated_ids": value["generated_ids"],
            "generated_ids_sha256": _digest(value["generated_ids"]), "reason": None,
            "catalog_context_utf8": data["catalog_context_raw"].decode("utf-8"),
            "catalog_context_sha256": data["expected_catalog_context_sha256"], "catalog_context_origin": data["catalog_context_origin"]}
        predictions = {"schema": PREDICTIONS_SCHEMA, "codec": value["inference_codec"], "codec_sha256": value["inference_codec_sha256"],
            "generation": {"kind": "decoder_declared", "population_sha256": data["expected_population_sha256"],
                "latent_dimension": 384, "checkpoint_sha256": data["expected_checkpoint_sha256"], "encoder_sha256": None,
                "settings_sha256": value["settings_sha256"], "teacher_forcing": exposure["teacher_forcing"],
                "target_access": exposure["target_access"]}, "rows": [observation]}
        result = dict(schema=BATCH_SCHEMA, profile=BATCH_PROFILE, generation_sha256=data["expected_report_sha256"],
            population_sha256=data["expected_population_sha256"], occurrence_id=data["occurrence_id"],
            population_raw_utf8=data["population_raw"].decode("utf-8"), generation_validation=validation,
            prediction_row=observation, predictions=predictions, predictions_sha256=_digest(predictions),
            source_context_sha256=source_row["context_sha256"], catalog_context_raw_sha256=data["expected_catalog_context_sha256"],
            encoder_sha256=None, generation_comparison_qualified=False, owner_pins=_pins(loaded),
            authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0,
            limitations=["The adapter performs one full numerical replay; its nested validation receipt describes that same work, not an additional execution.",
                "Referenced original forward counts are historical. Replay counters overlap and must not be summed.",
                "The complete original selected population remains unchanged. This one-row envelope leaves other occurrences missing; the existing evaluator preserves all observations and failures.",
                "Selected source-context and catalog-wrapper identities remain separate caller commitments, not authenticated source provenance.",
                "encoder_sha256 stays null. decoder_declared remains unverifiable_generation and no generation comparison credit is granted.",
                "Supplied prefixes, teacher-forcing and target-derived origin declarations are preserved; numerical execution cannot turn them into target-free generation."])
        result.update(_replay_accounting(count))
        fence()
        return result
    return _operation(original, work, preflight)


__all__ = ["CompactCatalogTrainedGenerationError", "generate_compact_catalog_trained_v1",
           "compact_catalog_trained_generation_sha256", "validate_compact_catalog_trained_generation_v1",
           "prepare_compact_catalog_trained_batch_prediction_v1"]
