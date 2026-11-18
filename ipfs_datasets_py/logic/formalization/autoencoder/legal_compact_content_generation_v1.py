"""Bounded orchestration of the existing numerical head and CONTENT intake.

The supplied prefix, conditioning and context remain observations. A numerical
forward establishes no source encoder, context permission or legal authority.
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

SCHEMA = "legal-compact-content-generation/v1"
PROFILE = "bounded-conditioning-compact-content-generation/v1"
BATCH_SCHEMA = "legal-compact-content-generation-batch-prediction/v1"
BATCH_PROFILE = "verified-trace-to-declared-content-observation/v1"
MAX_SEQUENCE_TOKENS = 512
MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
MAX_CONTEXT_BYTES = 524288
MAX_POPULATION_BYTES = 128 * 1024
MAX_INPUT_BYTES = 96 * 1024 * 1024
MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_JSON_ITEMS, MAX_JSON_DEPTH = 8_000_000, 96
MAX_SOURCE_BYTES = 4 * 1024 * 1024
PREFIX_ORIGINS = ("bos_seed", "authored_fixture", "target_derived_label", "caller_supplied_unverified")
CONTEXT_ORIGINS = ("authored_fixture", "target_derived_label", "caller_supplied_unverified")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
# The head is a separately authored producer. This observed generation must be
# refreshed only after its author freezes a reviewed replacement, before enroll.
_SOURCE_SPECS = (
    ("head", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_head_v1",
     "logic/formalization/autoencoder/legal_compact_content_head_v1.py",
     "8e32341e5962c01193ec46313011b83ba67b340a8996f866e417b10179b5c021"),
    ("tokens", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_tokens_v1",
     "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    (None, None, "logic/formalization/autoencoder/legal_compact_content_selection_v1.py",
     "936b476ea86a406a8c73937bbff9726dcaa3b2314b84b067064d8a618d1ee656"),
    ("batch", "ipfs_datasets_py.logic.autoformal.legal_relational_batch_evaluation_v1",
     "logic/autoformal/legal_relational_batch_evaluation_v1.py",
     "663af1184aeb73d10213e9953fee501303119de076886fa526dabff2b16d2138"),
    (None, None, "optimizers/logic_theorem_optimizer/modal_latent_formula.py",
     "ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36"),
    (None, None, "optimizers/logic_theorem_optimizer/domain_384_autoencoder.py",
     "66c5ee320f9c7aacd3b246d0666c7fc3ee928e4679892e1e90c838e1b291dbc6"),
    (None, None, "logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
)
_AUTHORITY = dict.fromkeys(("source_semantics_verified", "source_bound", "source_encoder_authenticated",
    "conditioning_producer_verified", "context_permission_verified", "prefix_origin_verified",
    "held_out_generation_verified", "training_qualified", "evaluation_gold_qualified",
    "legal_accuracy_established", "convergence_proved", "accepted", "admitted", "Lean_admitted"), False)
_LIMITATIONS = [
    "Conditioning, context origin and prefix origin are caller observations; no source encoder or permitted context is authenticated.",
    "Initial prefix IDs are supplied. Only selected_token_ids were emitted by these numerical decisions; generated_ids includes the supplied prefix.",
    "raw_argmax_ids_by_step records raw maxima evaluated along the constrained selected prefixes, not an independently autoregressed unconstrained trajectory.",
    "A seeded or exposed-prefix continuation is not a complete source-generated prediction or held-out accuracy measurement.",
    "The existing head owns numerical forwards and selector calls. This coordinator provides no optimizer updates, alternative grammar, source embedding or denominator.",
    "Whole finite traces belong in indexed artifacts addressed by content hashes. Compact lexical geometry does not establish provider-token savings or justify injecting full traces into supervisor prompts.",
    "Named source/input fences are finite custody checks, not a hermetic interpreter, arbitrary loaded-bytecode proof or third-party binary attestation.",
]
_REPORT_FIELDS = {"schema", "profile", "status", "reason", "checkpoint_sha256", "weights_sha256", "codec_sha256",
    "conditioning", "conditioning_sha256", "initial_prefix_ids", "prefix_origin", "context_origin",
    "context_raw_sha256", "context_sha256", "settings", "settings_sha256", "trace", "selected_token_ids",
    "raw_argmax_ids_by_step", "generated_ids", "emitted_token_count", "total_token_count", "score_call_count",
    "numerical_forward_count", "final_prefix_report", "final_decoding", "exposure", "model_executed",
    "training_executed", "compact_optimizer_executed", "owner_pins", "authority", "training_mask",
    "evaluation_gold_mask", "limitations"}


class CompactContentGenerationError(ValueError):
    """Input, whole bound, source generation or cross-owner commitment failed."""


def _need(ok, message):
    if not ok:
        raise CompactContentGenerationError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, "independent SHA256 required: " + label)


def _copy(value, maximum, *, allow_bytes=False):
    remaining, items, active = maximum, MAX_JSON_ITEMS, set()
    def charge(count):
        nonlocal remaining
        remaining -= count
        _need(remaining >= 0, "whole JSON byte bound exceeded")
    def text(item):
        _need(len(item) <= maximum, "bounded string required")
        charge(2)
        for character in item:
            code = ord(character)
            _need(code != 0 and not 0xD800 <= code <= 0xDFFF, "ordinary scalar UTF8 required")
            if character in ('"', "\\") or character in "\b\f\n\r\t":
                charge(2)
            elif code < 32:
                charge(6)
            else:
                charge(1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
    def visit(item, depth):
        nonlocal items
        items -= 1
        _need(items >= 0 and depth <= MAX_JSON_DEPTH, "whole JSON item/depth bound exceeded")
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
                    if index: charge(1)
                    result.append(visit(child, depth + 1))
                return result
            finally:
                active.remove(id(item))
        if type(item) is bytes and allow_bytes:
            charge(len(item))
        elif type(item) is str:
            text(item)
        elif item is None or type(item) is bool:
            charge(4 if item is None or item is True else 5)
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded plain integer required")
            charge(len(str(item)))
        elif type(item) is float:
            _need(math.isfinite(item), "finite plain numbers required")
            charge(len(repr(item)))
        else:
            raise CompactContentGenerationError("ordinary JSON containers/primitives required")
        return item
    try:
        return visit(value, 0)
    except (RuntimeError, RecursionError) as error:
        raise CompactContentGenerationError("stable bounded ordinary input required") from error


def _wire(value, maximum=MAX_REPORT_BYTES):
    checked = _copy(value, maximum)
    raw = json.dumps(checked, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    _need(len(raw) <= maximum, "complete serialized bound exceeded; truncation refused")
    return raw


def _digest(value, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(_wire(value, maximum)).hexdigest()


def _fingerprint(value):
    digest = hashlib.sha256()
    def visit(item):
        if type(item) is dict:
            digest.update(b"d" + str(len(item)).encode() + b":")
            for key in sorted(item): visit(key); visit(item[key])
        elif type(item) is list:
            digest.update(b"l" + str(len(item)).encode() + b":")
            for child in item: visit(child)
        elif type(item) is bytes:
            digest.update(b"b" + str(len(item)).encode() + b":" + item)
        else:
            digest.update(b"j" + _wire(item, MAX_INPUT_BYTES))
    visit(value)
    return digest.hexdigest()


def _source(path, expected):
    _need(path.is_absolute() and all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents), "unaliased source parents required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_SOURCE_BYTES, "bounded single-link source required")
    witness = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        _need(witness(os.fstat(stream.fileno())) == witness(before), "source changed before read")
        raw = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    _need(witness(before) == witness(after) == witness(path.lstat()) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected, "source witness or raw pin changed")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}, witness(after)


def _sources():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SOURCE_SPECS[1][2]).is_file():
                _need(candidate.resolve() == candidate, "canonical source tree required")
                root = candidate
                break
        if root is not None: break
    _need(root is not None, "canonical dependencies unavailable")
    observed = [_source(_SELF_PATH, _SELF_SHA), *[_source(root / relative, sha) for _, _, relative, sha in _SOURCE_SPECS]]
    return root, observed


def _owners():
    root, observed = _sources()
    modules = {}
    failure = None
    try:
        for key, name, relative, _ in _SOURCE_SPECS:
            if key is not None:
                module = importlib.import_module(name)
                _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative, "canonical public owner origin required")
                modules[key] = module
        return root, observed, modules
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _need(_sources() == (root, observed), "source changed during lazy imports")
        except BaseException:
            if failure is None: raise
            BaseException.add_note(failure, "A closing lazy-import source check also failed.")


def _operation(original, work):
    snapshot = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    token = _fingerprint(snapshot)
    loaded, failure = None, None
    def fence():
        _need(_fingerprint(_copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
              and _fingerprint(snapshot) == token, "original or detached operation inputs changed")
        if loaded is not None:
            root, observed, modules = loaded
            _need(_sources() == (root, observed), "operation source custody changed")
            for key, _, relative, _ in _SOURCE_SPECS:
                if key is not None:
                    _need(Path(modules[key].__file__).absolute() == root / relative, "public owner origin changed")
    try:
        loaded = _owners()
        result = work(snapshot, loaded, fence)
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
            if failure is None: raise
            BaseException.add_note(failure, "A closing generation input/source custody check also failed.")


def _inputs(checkpoint, conditioning, prefix_ids, context_raw, expected_checkpoint_sha256,
            expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    value = dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids, context_raw=context_raw,
        expected_checkpoint_sha256=expected_checkpoint_sha256, expected_context_sha256=expected_context_sha256,
        max_new_tokens=max_new_tokens, prefix_origin=prefix_origin, context_origin=context_origin)
    checked = _copy(value, MAX_INPUT_BYTES, allow_bytes=True)
    for key in ("expected_checkpoint_sha256", "expected_context_sha256"): _hash(checked[key], key)
    _need(type(checked["checkpoint"]) is dict and _digest(checked["checkpoint"], MAX_CHECKPOINT_BYTES) == expected_checkpoint_sha256, "complete checkpoint commitment differs")
    _need(type(checked["conditioning"]) is list and len(checked["conditioning"]) == 384
          and all(type(x) in (int, float) and math.isfinite(x) for x in checked["conditioning"]), "plain384 conditioning vector required")
    _need(type(checked["prefix_ids"]) is list and 1 <= len(checked["prefix_ids"]) <= MAX_SEQUENCE_TOKENS
          and all(type(x) is int for x in checked["prefix_ids"]), "nonempty bounded plain integer prefix required")
    _need(type(max_new_tokens) is int and 1 <= max_new_tokens <= MAX_SEQUENCE_TOKENS, "bounded positive new-token allowance required")
    _need(type(prefix_origin) is str and prefix_origin in PREFIX_ORIGINS and (prefix_origin != "bos_seed" or checked["prefix_ids"] == [1]), "declared prefix origin differs")
    _need(type(context_origin) is str and context_origin in CONTEXT_ORIGINS, "declared context origin differs")
    _need(type(context_raw) is bytes and 0 < len(context_raw) <= MAX_CONTEXT_BYTES
          and hashlib.sha256(context_raw).hexdigest() == expected_context_sha256, "raw context commitment differs")
    return value


def _producer_rows(report, loaded, expected_paths):
    rows = report["owner_pins"]
    available = {row[0]["path"]: row[0] for row in loaded[1]}
    _need(type(rows) is list and len(rows) == len(expected_paths), "complete public producer population required")
    _need(all(type(row) is dict and row == available.get(row.get("path")) for row in rows)
          and {row["path"] for row in rows} == expected_paths, "public producer descriptors differ")
    _need(type(report["authority"]) is dict and report["authority"] and all(x is False for x in report["authority"].values())
          and type(report["training_mask"]) is int and report["training_mask"] == 0
          and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0, "public authority or masks differ")


def generate_compact_content_v1(checkpoint, conditioning, prefix_ids, context_raw, *, expected_checkpoint_sha256,
        expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    """Continue an explicit supplied prefix; emit no more than the finite allowance."""
    original = _inputs(checkpoint, conditioning, prefix_ids, context_raw, expected_checkpoint_sha256,
        expected_context_sha256, max_new_tokens, prefix_origin, context_origin)
    def work(data, loaded, fence):
        root, observed, modules = loaded
        head, tokens = modules["head"], modules["tokens"]
        # The first public score call validates the full checkpoint and fixed
        # codec. A terminal prefix therefore retains head's no-restore path.
        checked, codec, codec_sha, options = data["checkpoint"], None, None, None
        head_paths = {str(root / _SOURCE_SPECS[i][2]) for i in (0, 1, 2, 4, 5)}
        token_paths = {str(root / _SOURCE_SPECS[i][2]) for i in (1, 6)}
        current, emitted, argmax, trace = list(data["prefix_ids"]), [], [], []
        settings = dict(max_new_tokens=data["max_new_tokens"], max_total_ids=MAX_SEQUENCE_TOKENS,
                        prefix_origin=data["prefix_origin"], context_origin=data["context_origin"])
        status = reason = final_prefix = None
        while True:
            if len(emitted) >= data["max_new_tokens"]:
                status, reason = "step_budget_exhausted", "max_new_tokens_reached"
                break
            fence()
            score = head.score_compact_content_head_v1(checked, data["conditioning"], current, data["context_raw"],
                expected_checkpoint_sha256=data["expected_checkpoint_sha256"], expected_context_sha256=data["expected_context_sha256"])
            fence()
            _producer_rows(score, loaded, head_paths)
            codec, codec_sha = checked["codec"], checked["codec_sha256"]
            options = dict(expected_context_sha256=data["expected_context_sha256"], codec=codec, expected_codec_sha256=codec_sha)
            _need(score["schema"] == "legal-compact-content-head-score/v1"
                  and score["checkpoint_sha256"] == data["expected_checkpoint_sha256"]
                  and score["weights_sha256"] == checked["weights_sha256"] and score["codec_sha256"] == codec_sha
                  and score["conditioning"] == data["conditioning"] and score["conditioning_sha256"] == _digest(data["conditioning"])
                  and score["prefix_ids"] == current and score["context_raw_sha256"] == data["expected_context_sha256"]
                  and score["optimizer_executed"] is False and score["compact_training_steps"] == 0,
                  "head report disagrees with original generation inputs")
            trace.append(score)
            final_prefix = score["prefix_report"]
            _producer_rows(final_prefix, loaded, token_paths)
            _need(final_prefix["offered_ids"] == current and final_prefix["context_raw_sha256"] == data["expected_context_sha256"]
                  and final_prefix["codec_sha256"] == codec_sha, "public prefix input commitments differ")
            if score["status"] == "no_forward":
                _need(score["numerical_forward_executed"] is score["model_restore_performed"] is False
                      and score["logits"] is score["logits_sha256"] is score["selection"] is score["output_shape"] is None
                      and score["next_prefix_ids"] == current and final_prefix["allowed_token_ids"] == [], "no-forward disposition differs")
                status = "supplied_complete" if not emitted and final_prefix["status"] == "complete" else "blocked"
                reason = "supplied_prefix_already_complete" if status == "supplied_complete" else (final_prefix["reason"] or final_prefix["status"])
                break
            selected = score["selection"]
            _need(score["status"] == "scored" and score["numerical_forward_executed"] is score["model_restore_performed"] is True
                  and type(score["logits"]) is list and len(score["logits"]) == 537
                  and all(type(x) is float and math.isfinite(x) for x in score["logits"])
                  and score["logits_sha256"] == _digest(score["logits"])
                  and selected["logits"] == score["logits"] and selected["logits_sha256"] == score["logits_sha256"]
                  and selected["offered_prefix_ids"] == current and selected["prefix_report"] == final_prefix
                  and selected["selection_performed"] is True and type(selected["selected_token_id"]) is int
                  and selected["selected_token_id"] in final_prefix["allowed_token_ids"]
                  and selected["next_prefix_ids"] == current + [selected["selected_token_id"]]
                  and score["next_prefix_ids"] == selected["next_prefix_ids"]
                  and len(current) < MAX_SEQUENCE_TOKENS, "complete score/selected-prefix binding differs")
            emitted.append(selected["selected_token_id"])
            argmax.append(selected["raw_argmax_token_id"])
            current = list(score["next_prefix_ids"])
            fence()
            final_prefix = tokens.compact_content_allowed_token_ids_v1(current, data["context_raw"], **options)
            fence()
            _producer_rows(final_prefix, loaded, token_paths)
            _need(final_prefix["offered_ids"] == current and final_prefix["context_raw_sha256"] == data["expected_context_sha256"]
                  and final_prefix["codec_sha256"] == codec_sha, "public next-prefix commitments differ")
            if final_prefix["status"] == "complete":
                status, reason = "complete", None
                break
            if not final_prefix["allowed_token_ids"]:
                status, reason = "blocked", final_prefix["reason"] or final_prefix["status"]
                break
        fence()
        decoded = tokens.decode_compact_content_tokens_v1(current, data["context_raw"], **options)
        fence()
        _producer_rows(decoded, loaded, token_paths)
        _need(decoded["generated_ids"] == current and decoded["context_raw_sha256"] == data["expected_context_sha256"]
              and decoded["codec_sha256"] == codec_sha and decoded["context_sha256"] == final_prefix["context_sha256"], "final token intake commitments differ")
        _need((status in ("complete", "supplied_complete")) == (decoded["status"] == "valid_candidate"), "generation terminal and token candidate disagree")
        exposure = dict(teacher_forcing=data["prefix_ids"] != [1],
            target_access=data["prefix_origin"] == "target_derived_label" or data["context_origin"] == "target_derived_label",
            source_encoder_authenticated=False, context_permission_verified=False, prefix_origin_verified=False, encoder_sha256=None)
        return dict(schema=SCHEMA, profile=PROFILE, status=status, reason=reason,
            checkpoint_sha256=data["expected_checkpoint_sha256"], weights_sha256=checked["weights_sha256"], codec_sha256=codec_sha,
            conditioning=data["conditioning"], conditioning_sha256=_digest(data["conditioning"]),
            initial_prefix_ids=data["prefix_ids"], prefix_origin=data["prefix_origin"], context_origin=data["context_origin"],
            context_raw_sha256=data["expected_context_sha256"], context_sha256=decoded["context_sha256"],
            settings=settings, settings_sha256=_digest(settings), trace=trace, selected_token_ids=emitted,
            raw_argmax_ids_by_step=argmax, generated_ids=current, emitted_token_count=len(emitted), total_token_count=len(current),
            score_call_count=len(trace), numerical_forward_count=len(emitted), final_prefix_report=final_prefix, final_decoding=decoded,
            exposure=exposure, model_executed=bool(emitted), training_executed=False, compact_optimizer_executed=False,
            owner_pins=[row[0] for row in observed], authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0,
            limitations=list(_LIMITATIONS))
    return _operation(original, work)


def compact_content_generation_sha256(report):
    """Closed report identity only, without importing numerical operation owners."""
    before = _source(_SELF_PATH, _SELF_SHA)
    checked = _copy(report, MAX_REPORT_BYTES)
    _need(type(checked) is dict and set(checked) == _REPORT_FIELDS and checked["schema"] == SCHEMA
          and checked["profile"] == PROFILE, "complete closed generation report required")
    result = _digest(checked)
    _need(_source(_SELF_PATH, _SELF_SHA) == before, "generation hash source changed")
    return result


def validate_compact_content_generation_v1(report, checkpoint, conditioning, prefix_ids, context_raw, *,
        expected_report_sha256, expected_checkpoint_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    """Require an independent report commitment and deterministic original replay."""
    _hash(expected_report_sha256, "complete generation report")
    offered = _copy(report, MAX_REPORT_BYTES)
    _need(compact_content_generation_sha256(offered) == expected_report_sha256, "independent generation report pin differs")
    original = _inputs(checkpoint, conditioning, prefix_ids, context_raw, expected_checkpoint_sha256,
        expected_context_sha256, max_new_tokens, prefix_origin, context_origin)
    original.update(report=report, expected_report_sha256=expected_report_sha256)
    def work(data, loaded, fence):
        _need(compact_content_generation_sha256(data["report"]) == data["expected_report_sha256"], "captured report commitment differs")
        regenerated = generate_compact_content_v1(data["checkpoint"], data["conditioning"], data["prefix_ids"], data["context_raw"],
            expected_checkpoint_sha256=data["expected_checkpoint_sha256"], expected_context_sha256=data["expected_context_sha256"],
            max_new_tokens=data["max_new_tokens"], prefix_origin=data["prefix_origin"], context_origin=data["context_origin"])
        fence()
        _need(_wire(data["report"]) == _wire(regenerated), "generation differs from complete original-bound replay")
        return regenerated
    return _operation(original, work)


def prepare_compact_content_generation_batch_prediction_v1(report, checkpoint, conditioning, prefix_ids, context_raw,
        population_raw, *, expected_generation_sha256, expected_population_sha256, occurrence_id,
        expected_checkpoint_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    """Link one verified continuation to one row of the unchanged CONTENT population."""
    _hash(expected_population_sha256, "original whole population")
    _need(type(population_raw) is bytes and 0 < len(population_raw) <= MAX_POPULATION_BYTES
          and hashlib.sha256(population_raw).hexdigest() == expected_population_sha256, "whole population commitment differs")
    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result, "duplicate population JSON key")
            result[key] = value
        return result
    population = json.loads(population_raw.decode(), object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(CompactContentGenerationError("finite population JSON required")))
    population = _copy(population, MAX_POPULATION_BYTES)
    _need(type(population) is dict and set(population) == {"schema", "partition", "selection_sha256", "rows"}
          and population["schema"] == "legal-relational-batch-population/v1" and type(population["rows"]) is list
          and 1 <= len(population["rows"]) <= 64, "existing complete population transport required")
    matching = [row for row in population["rows"] if type(row) is dict and row.get("id") == occurrence_id]
    _need(len(matching) == 1 and type(occurrence_id) is str and 0 < len(occurrence_id) <= 256, "one declared population occurrence required")
    row = matching[0]
    _need(set(row) == {"id", "source_sha256", "context_sha256"}, "closed existing population row required")
    for key in ("source_sha256", "context_sha256"): _hash(row[key], key)
    original = _inputs(checkpoint, conditioning, prefix_ids, context_raw, expected_checkpoint_sha256,
        expected_context_sha256, max_new_tokens, prefix_origin, context_origin)
    original.update(report=report, population=population, population_raw=population_raw,
        expected_generation_sha256=expected_generation_sha256, expected_population_sha256=expected_population_sha256,
        occurrence_id=occurrence_id)
    def work(data, loaded, fence):
        value = validate_compact_content_generation_v1(data["report"], data["checkpoint"], data["conditioning"], data["prefix_ids"], data["context_raw"],
            expected_report_sha256=data["expected_generation_sha256"], expected_checkpoint_sha256=data["expected_checkpoint_sha256"],
            expected_context_sha256=data["expected_context_sha256"], max_new_tokens=data["max_new_tokens"],
            prefix_origin=data["prefix_origin"], context_origin=data["context_origin"])
        fence()
        _need(loaded[2]["batch"].CONTENT_PREDICTIONS_SCHEMA == "legal-relational-content-token-batch-predictions/v1", "existing CONTENT schema differs")
        source_row = next(row for row in data["population"]["rows"] if type(row) is dict and row.get("id") == data["occurrence_id"])
        exposure = value["exposure"]
        observation = {**source_row, "status": "generated", "teacher_forcing": exposure["teacher_forcing"], "target_access": exposure["target_access"],
            "generated_ids": value["generated_ids"], "generated_ids_sha256": _digest(value["generated_ids"]), "reason": None,
            "content_context_utf8": data["context_raw"].decode(), "content_context_sha256": value["context_raw_sha256"],
            "content_context_origin": value["context_origin"]}
        predictions = {"schema": loaded[2]["batch"].CONTENT_PREDICTIONS_SCHEMA, "codec": data["checkpoint"]["codec"],
            "codec_sha256": value["codec_sha256"], "generation": {"kind": "decoder_declared",
                "population_sha256": data["expected_population_sha256"], "latent_dimension": 384,
                "checkpoint_sha256": value["checkpoint_sha256"], "encoder_sha256": None,
                "settings_sha256": value["settings_sha256"], "teacher_forcing": exposure["teacher_forcing"],
                "target_access": exposure["target_access"]}, "rows": [observation]}
        fence()
        return dict(schema=BATCH_SCHEMA, profile=BATCH_PROFILE, generation_sha256=data["expected_generation_sha256"],
            generation_report_sha256=data["expected_generation_sha256"], population_sha256=data["expected_population_sha256"],
            occurrence_id=data["occurrence_id"], prediction_row=observation, predictions=predictions,
            authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0,
            limitations=["This adapter links a replayed generation report but the existing batch evaluator does not authenticate that trace automatically.",
                "encoder_sha256 is null because no source encoder exists in this profile; decoder_declared therefore remains unverifiable_generation with no comparison credit.",
                "Source/model-context identities and the whole selected population remain caller declarations. One row leaves every other occurrence missing under the existing evaluator.",
                "generated_ids retains the supplied prefix plus selected IDs; exposure flags do not prove permission or target absence."])
    return _operation(original, work)


__all__ = ["CompactContentGenerationError", "generate_compact_content_v1", "compact_content_generation_sha256",
           "validate_compact_content_generation_v1", "prepare_compact_content_generation_batch_prediction_v1"]
