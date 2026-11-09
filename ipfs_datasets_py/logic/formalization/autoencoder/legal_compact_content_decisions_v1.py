"""Pure, target-exposed compact grammar inventories and saved-score diagnostics.

The pinned token owner alone determines admissibility. Typed-tree traversal
annotates its already validated canonical token stream; it creates no grammar,
model, optimizer, checkpoint, permitted context, or legal authority.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import stat

SCHEMA = "legal-compact-content-decisions/v1"
PROFILE = "all-predicates-prefix-decisions/v1"
ANALYSIS_SCHEMA = "legal-compact-saved-score-diagnostics/v1"
ANALYSIS_PROFILE = "bound-saved-full537-scalar-diagnostics/v1"
SCORES_SCHEMA = "legal-compact-saved-score-population/v1"
ROLES = ("transport", "constructor", "modal_letter", "predicate_reference",
         "variable_reference", "binder_declaration", "eos")
MAX_CONTENT_BYTES, MAX_CONTEXT_BYTES = 262144, 524288
MAX_SCORES_BYTES, MAX_INPUT_BYTES, MAX_REPORT_BYTES = 8 * 1024**2, 10 * 1024**2, 8 * 1024**2
MAX_ROW_BYTES, MAX_SOURCE_BYTES = 65536, 131072
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SPECS = (
    ("helper", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_selection_v1",
     "logic/formalization/autoencoder/legal_compact_content_selection_v1.py",
     "936b476ea86a406a8c73937bbff9726dcaa3b2314b84b067064d8a618d1ee656"),
    ("tokens", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_tokens_v1",
     "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    (None, None, "logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
)
_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_encoder_authenticated", "legal_roles_verified",
    "permitted_inference_context_verified", "target_independence_verified",
    "checkpoint_execution_authenticated", "logits_origin_authenticated",
    "source_observation_authenticated", "training_gold_qualified", "evaluation_gold_qualified",
    "applicability_verified", "accepted", "admitted", "proof_authority", "Lean_admitted",
    "global_prefix_completability_proven",
), False)
_LIMITATIONS = (
    "The complete offered target is exposed and every inspected prefix is teacher-forced; this is not free-running evaluation.",
    "Roles annotate validated syntax, not legal meaning. A grammar-forced semantic slot is distinct from transport punctuation.",
    "Allowed sets are immediate local grammar constraints; no global completion or legal correctness guarantee follows.",
    "Context, checkpoint, conditioning and observation hashes are commitments, not permission, source grounding or authenticated execution.",
    "Saved logits are supplied observations. This operation executes no model, training, optimizer, solver or Lean build.",
    "A singleton allowed set has zero conditional NLL regardless of model quality; full537 and conditional NLL remain separate.",
    "Missing scores remain unavailable. Partial observed means are not complete objectives or complete-population accuracy.",
    "Positive position weights define a scalar full537 diagnostic only; no masked loss, trainer integration or checkpoint mutation occurs.",
    "Source and input endpoint fences are finite custody checks, not a lock or attestation of arbitrary loaded bytecode.",
)


class CompactContentDecisionsError(ValueError):
    """Closed input, identity, bounded grammar annotation or score refusal."""


def _need(value, message):
    if not value:
        raise CompactContentDecisionsError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, "lowercase SHA256 required: " + label)


def _raw(raw, expected, maximum, label):
    _hash(expected, label)
    _need(type(raw) is bytes and 0 < len(raw) <= maximum
          and hashlib.sha256(raw).hexdigest() == expected, "raw byte commitment differs: " + label)


def _parse(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def integer(value):
        _need(len(value) <= 20, "bounded JSON integer required")
        result = int(value)
        _need(-(1 << 63) < result < (1 << 63), "bounded JSON integer required")
        return result
    def number(value):
        result = float(value)
        _need(math.isfinite(result), "finite JSON number required")
        return result
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
            parse_int=integer, parse_float=number,
            parse_constant=lambda _: (_ for _ in ()).throw(CompactContentDecisionsError("nonfinite JSON refused")))
    except (UnicodeError, RecursionError, json.JSONDecodeError) as error:
        raise CompactContentDecisionsError("bounded ordinary UTF8 JSON required") from error


def _source(path, expected):
    _need(path.is_absolute() and path.resolve(strict=True) == path, "unaliased source required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
          and 0 < before.st_size <= MAX_SOURCE_BYTES, "bounded single-link source required")
    raw = path.read_bytes()
    after = path.lstat()
    witness = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    _need(witness(before) == witness(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected, "pinned source changed")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}, witness(after)


def _sources():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SPECS[1][2]).is_file():
                _need(candidate.resolve() == candidate, "canonical dependency root required")
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "canonical dependencies unavailable")
    return root, [_source(_SELF_PATH, _SELF_SHA), *[_source(root / rel, sha) for _, _, rel, sha in _SPECS]]


def _operation(original, work):
    root, observed = _sources()
    modules, snapshot, token, failure = {}, None, None, None
    def fence():
        _need(_sources() == (root, observed), "diagnostic source custody changed")
        for key, _, relative, _ in _SPECS:
            if key in modules:
                _need(Path(modules[key].__file__).absolute() == root / relative, "loaded public origin changed")
        if token is not None:
            helper = modules["helper"]
            _need(helper._fingerprint(helper._copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
                  and helper._fingerprint(snapshot) == token, "original or captured inputs changed")
    try:
        for key, name, relative, _ in _SPECS:
            if key is not None:
                module = importlib.import_module(name)
                _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                      "canonical public owner origin required")
                modules[key] = module
        helper = modules["helper"]
        snapshot = helper._copy(original, MAX_INPUT_BYTES, allow_bytes=True)
        token = helper._fingerprint(snapshot)
        fence()
        result = work(snapshot, modules, observed, fence)
        raw = helper._wire(result, MAX_REPORT_BYTES)
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
            BaseException.add_note(failure, "A closing diagnostic input/source custody check also failed.")


def _digest(value, helper, maximum=MAX_REPORT_BYTES):
    return hashlib.sha256(helper._wire(value, maximum)).hexdigest()


def _public(report, observed):
    available = {row[0]["path"]: row[0] for row in observed[2:]}
    rows = report["owner_pins"]
    _need(type(rows) is list and len(rows) == 2 and {row["path"] for row in rows} == set(available)
          and all(row == available[row["path"]] for row in rows), "public token producer population differs")
    _need(type(report["authority"]) is dict and report["authority"]
          and all(value is False for value in report["authority"].values())
          and type(report["training_mask"]) is type(report["evaluation_gold_mask"]) is int
          and report["training_mask"] == report["evaluation_gold_mask"] == 0, "public token authority differs")


def _annotations(content):
    """Annotate only the public encoder's validated tree; never admit a prefix."""
    result = []
    def emit(token, role="transport", path=()):
        _need(len(result) < 510, "annotation exceeds complete token bound")
        result.append({"lexical_token": token, "role": role, "tree_path": list(path)})
    def literal(value, role="transport", path=()):
        emit(json.dumps(value, ensure_ascii=False, separators=(",", ":")), role, path)
    def tree(node, path, depth):
        _need(depth <= 48 and type(node) is list and node, "validated annotation tree required")
        kind = node[0]
        emit("[", path=path); literal(kind, "constructor", (*path, 0)); emit(",", path=path)
        if kind == "variable":
            literal(node[1], "variable_reference", (*path, 1))
        elif kind == "predicate":
            literal(node[1], "predicate_reference", (*path, 1)); emit(",", path=path); emit("[", path=(*path, 2))
            for index, child in enumerate(node[2]):
                if index: emit(",", path=(*path, 2))
                tree(child, (*path, 2, index), depth + 1)
            emit("]", path=(*path, 2))
        elif kind in ("forall", "exists"):
            literal(node[1], "binder_declaration", (*path, 1)); emit(",", path=path)
            tree(node[2], (*path, 2), depth + 1)
        elif kind in ("and", "or", "implies", "iff"):
            tree(node[1], (*path, 1), depth + 1); emit(",", path=path); tree(node[2], (*path, 2), depth + 1)
        elif kind == "not":
            tree(node[1], (*path, 1), depth + 1)
        elif kind == "extension":
            literal(node[1], "modal_letter", (*path, 1)); emit(",", path=path); tree(node[2], (*path, 2), depth + 1)
        else:
            raise CompactContentDecisionsError("validated constructor has no role annotation")
        emit("]", path=path)
    for token in ("{", '"schema"', ":", json.dumps(content["schema"]), ",", '"tree"', ":"):
        emit(token)
    tree(content["tree"], ("tree",), 0)
    emit("}")
    return result


def _prepare(data, modules, observed, fence):
    tokens, helper = modules["tokens"], modules["helper"]
    _raw(data["content_raw"], data["expected_content_sha256"], MAX_CONTENT_BYTES, "content")
    _raw(data["context_raw"], data["expected_context_sha256"], MAX_CONTEXT_BYTES, "context")
    _hash(data["expected_codec_sha256"], "codec")
    _need(tokens.compact_content_token_codec_sha256(data["codec"]) == data["expected_codec_sha256"],
          "exact all-predicates codec required")
    options = dict(expected_context_sha256=data["expected_context_sha256"], codec=data["codec"],
                   expected_codec_sha256=data["expected_codec_sha256"])
    fence()
    encoded = tokens.encode_compact_content_tokens_v1(data["content_raw"], data["context_raw"],
        expected_content_sha256=data["expected_content_sha256"], **options)
    fence(); _public(encoded, observed)
    canonical = helper._wire(_parse(data["content_raw"]), MAX_CONTENT_BYTES)
    _need(encoded["schema"] == "legal-compact-content-token-encoding/v1"
          and encoded["status"] == "encoded_unreviewed_content"
          and encoded["original_content_raw_sha256"] == data["expected_content_sha256"]
          and encoded["canonical_content_raw_utf8"].encode("utf-8") == canonical
          and encoded["content_sha256"] == hashlib.sha256(canonical).hexdigest()
          and encoded["context_raw_sha256"] == data["expected_context_sha256"]
          and encoded["codec_sha256"] == data["expected_codec_sha256"], "public encoding identity differs")
    annotations = _annotations(_parse(canonical))
    lexical = [row["lexical_token"] for row in annotations]
    vocabulary = data["codec"]["vocabulary"]
    token_ids = {text: index for index, text in enumerate(vocabulary)}
    _need(lexical == encoded["lexical_tokens"] and "".join(lexical).encode("utf-8") == canonical,
          "typed annotation and validated lexical stream differ")
    ids = [1, *(token_ids[text] for text in lexical), 2]
    _need(ids == encoded["target_ids"] and len(ids) == encoded["total_token_count"] <= 512,
          "complete target framing differs")
    positions = []
    for index, annotation in enumerate([*annotations, {"lexical_token": "<eos>", "role": "eos", "tree_path": []}], 1):
        prefix = ids[:index]
        report = tokens.compact_content_allowed_token_ids_v1(prefix, data["context_raw"], **options)
        fence(); _public(report, observed)
        allowed = report["allowed_token_ids"]
        _need(report["schema"] == "legal-compact-content-token-prefix/v1" and report["status"] == "prefix"
              and report["reason"] is None and report["offered_ids"] == prefix
              and report["codec_sha256"] == data["expected_codec_sha256"]
              and report["context_raw_sha256"] == data["expected_context_sha256"]
              and report["context_sha256"] == encoded["context_sha256"]
              and report["local_prefix_only"] is True and report["global_completability_proven"] is False
              and type(allowed) is list and all(type(value) is int and 0 <= value < 537 for value in allowed)
              and allowed == sorted(set(allowed)) and ids[index] in allowed,
              "complete target position is not admitted by public prefix owner")
        positions.append(dict(target_position=index, prefix_length=index,
            prefix_ids_sha256=_digest(prefix, helper), target_token_id=ids[index], **annotation,
            decision_kind="forced" if len(allowed) == 1 else "choice", allowed_token_ids=allowed,
            allowed_count=len(allowed), prefix_report_sha256=_digest(report, helper),
            prefix_status=report["status"], local_prefix_only=True, global_completability_proven=False))
    tally = Counter(row["role"] for row in positions)
    forced = sum(row["decision_kind"] == "forced" for row in positions)
    return dict(schema=SCHEMA, profile=PROFILE, content_raw_sha256=data["expected_content_sha256"],
        canonical_content_sha256=encoded["content_sha256"], context_raw_sha256=data["expected_context_sha256"],
        context_sha256=encoded["context_sha256"], codec_sha256=data["expected_codec_sha256"], target_ids=ids,
        target_ids_sha256=_digest(ids, helper), encoding_report_sha256=_digest(encoded, helper), positions=positions,
        counts=dict(supervised_positions=len(positions), forced_positions=forced,
                    choice_positions=len(positions) - forced, by_role={role: tally[role] for role in ROLES}),
        owner_pins=[row[0] for row in observed], teacher_forcing=True, target_access=True,
        model_executed=False, training_executed=False, authority=dict(_AUTHORITY),
        training_mask=0, evaluation_gold_mask=0, limitations=list(_LIMITATIONS))


def prepare_compact_content_decisions_v1(content_raw, context_raw, *, expected_content_sha256,
                                        expected_context_sha256, codec, expected_codec_sha256):
    """Inventory every teacher-forced target position using the public grammar."""
    return _operation(dict(content_raw=content_raw, context_raw=context_raw,
        expected_content_sha256=expected_content_sha256, expected_context_sha256=expected_context_sha256,
        codec=codec, expected_codec_sha256=expected_codec_sha256), _prepare)


def _score_packet(data, inventory, helper):
    _raw(data["scores_raw"], data["expected_scores_sha256"], MAX_SCORES_BYTES, "saved scores")
    for name in ("expected_checkpoint_sha256", "expected_conditioning_sha256"):
        _hash(data[name], name)
    value = _parse(data["scores_raw"])
    fields = {"schema", "target_raw_sha256", "context_raw_sha256", "codec_sha256",
              "checkpoint_sha256", "conditioning_sha256", "rows"}
    _need(type(value) is dict and set(value) == fields and value["schema"] == SCORES_SCHEMA,
          "closed saved score population required")
    for key, expected in (("target_raw_sha256", data["expected_content_sha256"]),
                          ("context_raw_sha256", data["expected_context_sha256"]),
                          ("codec_sha256", data["expected_codec_sha256"]),
                          ("checkpoint_sha256", data["expected_checkpoint_sha256"]),
                          ("conditioning_sha256", data["expected_conditioning_sha256"])):
        _hash(value[key], key); _need(value[key] == expected, "saved score header identity differs: " + key)
    rows = value["rows"]
    _need(type(rows) is list and len(rows) <= len(inventory["positions"]), "bounded saved position population required")
    result, previous = {}, 0
    for offered in rows:
        # Bound each row separately: a full511-position packet legitimately
        # exceeds the shared helper's100000-item whole-value budget.
        row = helper._copy(offered, MAX_ROW_BYTES)
        _need(type(row) is dict and set(row) == {"prefix_ids", "logits", "logits_sha256", "source_observation_sha256"},
              "closed saved score row required")
        prefix, logits = row["prefix_ids"], row["logits"]
        _need(type(prefix) is list and previous < len(prefix) < len(inventory["target_ids"])
              and all(type(token) is int for token in prefix)
              and prefix == inventory["target_ids"][:len(prefix)], "ordered exact target prefixes required")
        _need(type(logits) is list and len(logits) == 537
              and all(type(score) in (int, float) and math.isfinite(score) and abs(score) <= 1e6 for score in logits),
              "bounded finite full537 saved scores required")
        for key in ("logits_sha256", "source_observation_sha256"):
            _hash(row[key], key)
        _need(_digest(logits, helper, MAX_ROW_BYTES) == row["logits_sha256"], "saved logits commitment differs")
        previous = len(prefix)
        result[previous] = row
    return result


def _metrics(logits, allowed, target):
    maximum = max(logits)
    exponentials = [math.exp(value - maximum) for value in logits]
    denominator = math.fsum(exponentials)
    top = max(logits[index] for index in allowed)
    legal_sum = math.fsum(math.exp(logits[index] - top) for index in allowed)
    full_nll = (maximum - logits[target]) + math.log(denominator)
    allowed_nll = (top - logits[target]) + math.log(legal_sum)
    permitted = set(allowed)
    forbidden = math.fsum(value for index, value in enumerate(exponentials) if index not in permitted) / denominator
    raw = max(range(537), key=lambda index: logits[index])
    constrained = max(allowed, key=lambda index: logits[index])
    _need(all(math.isfinite(x) for x in (full_nll, allowed_nll, forbidden))
          and full_nll >= 0 and allowed_nll >= 0 and 0 <= forbidden <= 1,
          "finite stable diagnostic metrics required")
    return dict(full537_nll=full_nll, allowed_nll=allowed_nll, forbidden_probability_mass=forbidden,
        raw_argmax_token_id=raw, constrained_argmax_token_id=constrained,
        raw_correct=raw == target, constrained_correct=constrained == target,
        selection_overrode_raw_argmax=raw != constrained)


def _summary(rows):
    observed = [row for row in rows if row["status"] == "observed"]
    count = len(observed)
    def mean(key):
        return math.fsum(row["metrics"][key] for row in observed) / count if count else None
    # Common scaling also keeps an all-subnormal positive policy well-defined.
    scale = max(row["weight"] for row in observed) if count else 1.0
    weighted = (math.fsum((row["weight"] / scale) * row["metrics"]["full537_nll"] for row in observed)
                / math.fsum(row["weight"] / scale for row in observed)) if count else None
    return dict(population_positions=len(rows), observed_positions=count, missing_positions=len(rows) - count,
        observed_mean_full537_nll=mean("full537_nll"), observed_mean_allowed_nll=mean("allowed_nll"),
        observed_mean_forbidden_probability_mass=mean("forbidden_probability_mass"),
        observed_weighted_full537_nll=weighted,
        raw_correct=sum(row["metrics"]["raw_correct"] for row in observed),
        constrained_correct=sum(row["metrics"]["constrained_correct"] for row in observed))


def analyze_compact_saved_scores_v1(content_raw, context_raw, scores_raw, *, expected_content_sha256,
        expected_context_sha256, codec, expected_codec_sha256, expected_scores_sha256,
        expected_checkpoint_sha256, expected_conditioning_sha256, forced_weight=1.0, choice_weight=1.0):
    """Diagnose committed observations; missing positions never become targets/logits."""
    original = dict(content_raw=content_raw, context_raw=context_raw, scores_raw=scores_raw,
        expected_content_sha256=expected_content_sha256, expected_context_sha256=expected_context_sha256,
        codec=codec, expected_codec_sha256=expected_codec_sha256, expected_scores_sha256=expected_scores_sha256,
        expected_checkpoint_sha256=expected_checkpoint_sha256, expected_conditioning_sha256=expected_conditioning_sha256,
        forced_weight=forced_weight, choice_weight=choice_weight)
    def work(data, modules, observed, fence):
        for key in ("forced_weight", "choice_weight"):
            value = data[key]
            _need(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 16,
                  "explicit positive position weight must be at most16")
        # Refuse a malformed/hash-mismatched raw packet before grammar traversal.
        _raw(data["scores_raw"], data["expected_scores_sha256"], MAX_SCORES_BYTES, "saved scores")
        inventory = _prepare(data, modules, observed, fence)
        helper = modules["helper"]
        saved = _score_packet(data, inventory, helper)
        fence()
        policy = dict(objective="weighted_full537_cross_entropy", forced_weight=float(data["forced_weight"]),
            choice_weight=float(data["choice_weight"]), normalization="sum_position_weights",
            complete_objective_requires_all_positions=True)
        rows = []
        for position in inventory["positions"]:
            record = saved.get(position["target_position"])
            rows.append(dict(target_position=position["target_position"], role=position["role"],
                decision_kind=position["decision_kind"], status="observed" if record else "unavailable",
                reason=None if record else "missing_saved_score", weight=policy[position["decision_kind"] + "_weight"],
                metrics=_metrics(record["logits"], position["allowed_token_ids"], position["target_token_id"]) if record else None,
                logits_sha256=record["logits_sha256"] if record else None,
                source_observation_sha256=record["source_observation_sha256"] if record else None))
        summary = _summary(rows)
        complete = len(saved) == len(rows)
        return dict(schema=ANALYSIS_SCHEMA, profile=ANALYSIS_PROFILE, inventory=inventory,
            inventory_sha256=_digest(inventory, helper), scores_raw_sha256=data["expected_scores_sha256"],
            checkpoint_sha256=data["expected_checkpoint_sha256"], conditioning_sha256=data["expected_conditioning_sha256"],
            policy=policy, policy_sha256=_digest(policy, helper), rows=rows,
            counts=dict(supervised_positions=len(rows), observed_positions=len(saved), missing_positions=len(rows) - len(saved)),
            observations_complete=complete,
            complete_weighted_full537_objective=summary["observed_weighted_full537_nll"] if complete else None,
            observed_summary=summary,
            by_role={role: _summary([row for row in rows if row["role"] == role]) for role in ROLES},
            by_decision_kind={kind: _summary([row for row in rows if row["decision_kind"] == kind]) for kind in ("forced", "choice")},
            owner_pins=[row[0] for row in observed], teacher_forcing=True, target_access=True,
            model_executed=False, training_executed=False, authority=dict(_AUTHORITY),
            training_mask=0, evaluation_gold_mask=0, limitations=list(_LIMITATIONS))
    return _operation(original, work)


__all__ = ["CompactContentDecisionsError", "prepare_compact_content_decisions_v1", "analyze_compact_saved_scores_v1"]
