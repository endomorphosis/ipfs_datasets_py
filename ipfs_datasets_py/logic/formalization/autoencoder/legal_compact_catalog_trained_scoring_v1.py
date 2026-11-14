"""One bounded trained CONTENT-weight forward with explicit catalog selection.

The original checkpoint and its training codec are never relabeled. Lexical
compatibility permits this engineering observation, not catalog training,
source/context permission, statutory accuracy or proof acceptance.
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


SCORE_SCHEMA = "legal-compact-catalog-trained-score/v1"
SCHEMA = SCORE_SCHEMA
PROFILE = "original-trained-content-weights-catalog-selection/v1"
BRIDGE_SCHEMA = "legal-compact-trained-catalog-lexical-bridge/v1"
DIMENSION, VOCABULARY_SIZE, MAX_SEQUENCE_TOKENS = 384, 537, 512
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
MAX_INPUT_BYTES, MAX_REPORT_BYTES = 96 * 1024 * 1024, 4 * 1024 * 1024
MAX_CONTEXT_BYTES, MAX_CODEC_BYTES, MAX_LOGITS_BYTES = 524288, 32768, 32768
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_JSON_ITEMS, MAX_JSON_DEPTH = 12_000_000, 96
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SELF_PATH = Path(__file__).absolute()
_SOURCE_SPECS = (
    ("trained", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_trained_runtime_v2",
     "logic/formalization/autoencoder/legal_compact_content_trained_runtime_v2.py",
     "43037fe64c58de0bcfc2072178eabe1276b4a020863e20b9498a634763b56e5a"),
    ("catalog", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_catalog_tokens_v1",
     "logic/formalization/autoencoder/legal_compact_catalog_tokens_v1.py",
     "bc9e425707c98db3425b5dafb1ab75e5c70002cbf6c229ef1f815eb9bb4612af"),
    ("selection", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_catalog_selection_v1",
     "logic/formalization/autoencoder/legal_compact_catalog_selection_v1.py",
     "b43880b5a2fc74bcc197860d01ce92540d3107b436a5f19d5a088bb757d99415"),
    (None, None, "logic/formalization/autoencoder/legal_compact_content_training_v2.py",
     "3ff34b8094a8bb19315741a03873c95f7d809654b35717fd4cee97e074fd2b59"),
    (None, None, "logic/formalization/autoencoder/legal_compact_content_head_v1.py",
     "8e32341e5962c01193ec46313011b83ba67b340a8996f866e417b10179b5c021"),
    (None, None, "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
    (None, None, "logic/formalization/autoencoder/legal_compact_content_selection_v1.py",
     "936b476ea86a406a8c73937bbff9726dcaa3b2314b84b067064d8a618d1ee656"),
    (None, None, "logic/autoformal/legal_relational_batch_evaluation_v1.py",
     "663af1184aeb73d10213e9953fee501303119de076886fa526dabff2b16d2138"),
    (None, None, "optimizers/logic_theorem_optimizer/modal_latent_formula.py",
     "ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36"),
    (None, None, "optimizers/logic_theorem_optimizer/domain_384_autoencoder.py",
     "66c5ee320f9c7aacd3b246d0666c7fc3ee928e4679892e1e90c838e1b291dbc6"),
    (None, None, "logic/autoformal/legal_compact_content_v1.py",
     "de6495ed91d6842071d0892c4410dfb9243fab658eb22d19635a8db599b4b25e"),
    (None, None, "logic/autoformal/legal_relational_norm_v1.py",
     "6af97bbe5bb729fc6218b77bc32551aaca5d2ed2ba89d61312937a3109032614"),
    (None, None, "logic/syntax_core/ast.py", "4709513f18ab270858fe9595d88a847ddc52092606c52c7802947abed1ab9ac4"),
    (None, None, "logic/syntax_core/signatures.py", "49dd4fb0096661a05a15f056eb57248349e2b4e0b02e83239f36db36788c75bf"),
    (None, None, "logic/TDFOL/tdfol_core.py", "67be350d1fb0422a64ab040349b2d51c4008fbeeb8b59a99b8901d681d7d71c7"),
)
_AUTHORITY = dict.fromkeys((
    "catalog_training_verified", "training_history_authenticated", "source_semantics_verified",
    "source_bound", "source_encoder_authenticated", "conditioning_producer_verified",
    "context_permission_verified", "permitted_inference_context_verified", "prefix_origin_verified",
    "prefix_independence_verified", "content_context_independence_verified", "held_out_generation_verified",
    "training_qualified", "training_gold_qualified", "evaluation_gold_qualified", "legal_accuracy_established",
    "statutory_accuracy_verified", "statutory_checkpoint_qualified", "source_fidelity_verified",
    "global_prefix_completability_proven", "convergence_proved", "accepted", "admitted",
    "proof_authority", "Lean_admitted"), False)
_SELECTION_FIELDS = {"schema", "profile", "format", "selection_policy", "status", "reason", "prefix_status",
    "logits", "logits_sha256", "offered_prefix_ids", "next_prefix_ids", "prefix_report", "prefix_report_sha256",
    "raw_argmax_token_id", "raw_argmax_score", "selected_token_id", "selected_score", "selection_performed",
    "selection_overrode_raw_argmax", "tokens_appended", "tie_breaker", "codec_sha256", "context_raw_sha256",
    "context_sha256", "catalog_sha256", "owner_pins", "logits_origin_verified", "head_compatibility_qualified",
    "authority", "training_mask", "evaluation_gold_mask", "limitations"}
_LIMITATIONS = [
    "The original trained CONTENT codec and the distinct catalog inference codec retain separate complete identities. The checkpoint is not catalog-trained or rewritten.",
    "Exact vocabulary, special-ID and sequence-geometry compatibility is a mechanical bridge, not training, source semantics, context permission or statutory accuracy.",
    "Conditioning and the nonempty prefix are caller-supplied observations; no source encoder, prefix independence or permitted catalog is authenticated.",
    "One actual forward is recorded even when grammar permits only EOS. A forced token is not evidence of a learned structural decision.",
    "A complete, rejected or blocked supplied prefix performs no numerical forward, model restoration or live-runtime verification.",
    "The independent checkpoint hash binds supplied state. A structurally valid new checkpoint may be consumed, but self-consistency does not authenticate historical training, lineage or a producer principal.",
    "This operation performs no replay/reference forward, optimizer construction, optimizer restore, update, training, generation loop or target/reference lookup.",
    "Endpoint source/input fences cover the declared finite source closure; they are not a lock, proof of arbitrary loaded bytecode, third-party binary attestation or operating-system containment.",
]


class CompactCatalogTrainedScoringError(ValueError):
    """Bounded input, lexical bridge, fixed-source or cross-owner refusal."""


def _need(value, message):
    if not value:
        raise CompactCatalogTrainedScoringError(message)


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
            raise CompactCatalogTrainedScoringError("ordinary JSON containers/primitives required")
        return item

    try:
        return visit(value, 0)
    except (RuntimeError, RecursionError) as error:
        raise CompactCatalogTrainedScoringError("stable bounded ordinary inputs required") from error


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
            if (candidate / _SOURCE_SPECS[0][2]).is_file():
                _need(candidate.resolve() == candidate, "canonical dependency root required")
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "pinned catalog/trained owners unavailable")
    snapshots = {str(_SELF_PATH): _snapshot(_SELF_PATH)}
    _need(snapshots[str(_SELF_PATH)] == _SELF_SNAPSHOT, "scoring owner changed since import")
    for _, _, relative, expected in _SOURCE_SPECS:
        path = root / relative
        snapshots[str(path)] = _snapshot(path)
        _need(snapshots[str(path)][0] == expected, "fixed scoring source generation differs")
    return root, snapshots


def _closing(loaded):
    root, snapshots, modules = loaded
    _need(_sources() == (root, snapshots), "catalog scoring physical source custody changed")
    for key, _, relative, _ in _SOURCE_SPECS:
        if key is not None:
            module = modules[key]
            path = root / relative
            _need(type(module.__file__) is str and Path(module.__file__).absolute() == path,
                  "canonical public owner origin changed")
            if key == "trained":
                _need(module._SELF_SHA == snapshots[str(path)][0], "trained runtime import anchor changed")
            else:
                _need(module._SELF_SNAPSHOT == snapshots[str(path)], "catalog owner import anchor changed")


def _owners():
    root, snapshots = _sources()
    modules, failure = {}, None
    try:
        for key, name, _, _ in _SOURCE_SPECS:
            if key is not None:
                modules[key] = importlib.import_module(name)
        loaded = root, snapshots, modules
        _closing(loaded)
        return loaded
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _need(_sources() == (root, snapshots), "source changed during lazy imports")
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing scoring lazy-import source fence also failed.")


def _operation(original, work):
    snapshot = _copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    token = _fingerprint(snapshot)
    loaded = None
    failure = None

    def fence():
        _need(_fingerprint(_copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token
              and _fingerprint(snapshot) == token, "original or captured scoring inputs changed")
        if loaded is not None:
            _closing(loaded)

    try:
        _preflight(snapshot)
        fence()
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
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing catalog scoring input/source custody check also failed.")


def _preflight(data):
    for name in ("expected_checkpoint_sha256", "expected_catalog_context_sha256"):
        _need(type(data[name]) is str and _SHA.fullmatch(data[name]) is not None,
              "independent lowercase SHA256 required: " + name)
    _need(type(data["checkpoint"]) is dict
          and _digest(data["checkpoint"], MAX_CHECKPOINT_BYTES) == data["expected_checkpoint_sha256"],
          "complete original checkpoint commitment differs")
    vector, prefix, raw = data["conditioning"], data["prefix_ids"], data["catalog_context_raw"]
    _need(type(vector) is list and len(vector) == DIMENSION
          and all(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e8 for value in vector),
          "bounded exact 384-value conditioning list required")
    _need(type(prefix) is list and 1 <= len(prefix) <= MAX_SEQUENCE_TOKENS
          and all(type(value) is int for value in prefix), "nonempty bounded plain-integer prefix required")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_CONTEXT_BYTES
          and hashlib.sha256(raw).hexdigest() == data["expected_catalog_context_sha256"],
          "complete original catalog context commitment differs")


def _pins(loaded, paths=None):
    return [{"path": path, "bytes": value[1][3], "sha256": value[0]}
            for path, value in sorted(loaded[1].items()) if paths is None or path in paths]


def _authority(report, expected):
    _need(type(report["authority"]) is dict and set(report["authority"]) == set(expected)
          and all(flag is False for flag in report["authority"].values())
          and type(report["training_mask"]) is int and report["training_mask"] == 0
          and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0,
          "public owner authority or masks differ")


def _producer_rows(report, loaded, relatives):
    expected = {row["path"]: row for row in _pins(loaded, {str(loaded[0] / relative) for relative in relatives})}
    rows = report["owner_pins"]
    _need(type(rows) is list and len(rows) == len(expected), "complete public producer inventory required")
    seen = set()
    for row in rows:
        _need(type(row) is dict and set(row) == {"path", "bytes", "sha256"}
              and type(row["path"]) is str and type(row["bytes"]) is int
              and row["path"] not in seen and row == expected.get(row["path"]),
              "public producer record differs")
        seen.add(row["path"])


def _bridge(checkpoint, inference, catalog):
    training = _copy(checkpoint["codec"], MAX_CODEC_BYTES)
    training_sha = _digest(training, MAX_CODEC_BYTES)
    inference_sha = catalog.compact_catalog_token_codec_sha256(inference)
    _need(training_sha == checkpoint["codec_sha256"] and inference_sha == _digest(inference, MAX_CODEC_BYTES)
          and inference["parent_codec_sha256"] == training_sha and training_sha != inference_sha,
          "distinct original training and catalog codec commitments required")
    geometry_fields = ("vocabulary_size", "pad_id", "bos_id", "eos_id", "max_sequence_tokens",
                       "max_nodes", "max_depth", "integer_min", "integer_max", "constructors")
    _need(_wire(training["vocabulary"], MAX_CODEC_BYTES) == _wire(inference["vocabulary"], MAX_CODEC_BYTES)
          and len(training["vocabulary"]) == VOCABULARY_SIZE
          and all(_wire(training[name], MAX_CODEC_BYTES) == _wire(inference[name], MAX_CODEC_BYTES)
                  for name in geometry_fields), "complete ordered vocabulary, special IDs or sequence geometry differ")
    _need(training["schema"] == "legal-compact-content-token-codec/v1"
          and inference["schema"] == "legal-compact-catalog-token-codec/v1"
          and inference["selection_policy"] == "referenced_predicates_in_catalog_order/v1"
          and [training[name] for name in ("pad_id", "bos_id", "eos_id")] == [0, 1, 2]
          and training["vocabulary"][:3] == ["<pad>", "<bos>", "<eos>"]
          and training["max_sequence_tokens"] == checkpoint["max_total_ids"] == MAX_SEQUENCE_TOKENS,
          "fixed codec identities, special-token meanings or sequence limit differ")
    bridge = {"schema": BRIDGE_SCHEMA, "training_codec_sha256": training_sha,
        "inference_codec_sha256": inference_sha, "ordered_vocabulary_equal": True,
        "ordered_vocabulary_sha256": _digest(training["vocabulary"], MAX_CODEC_BYTES),
        "special_ids": {name: training[name] for name in ("pad_id", "bos_id", "eos_id")},
        "sequence_geometry": {name: training[name] for name in geometry_fields
                              if name not in {"pad_id", "bos_id", "eos_id"}},
        "training_grammar_scope": training["grammar_scope"], "inference_grammar_scope": inference["grammar_scope"],
        "inference_selection_policy": inference["selection_policy"],
        "policy_difference": "complete_predicate_use_to_nonempty_catalog_subset/v1",
        "catalog_training_verified": False}
    return training, training_sha, inference_sha, bridge


def _prefix_report(offered, data, codec_sha, loaded):
    report = _copy(offered, 2 * 1024 * 1024)
    catalog, selector = loaded[2]["catalog"], loaded[2]["selection"]
    _need(type(report) is dict and set(report) == selector._PREFIX_FIELDS
          and report["schema"] == "legal-compact-catalog-token-prefix/v1"
          and report["profile"] == "object-relational-compact-catalog-tokens/v1"
          and report["format"] == "fixed-json-lexical-compact-catalog/v1"
          and report["selection_policy"] == "referenced_predicates_in_catalog_order/v1"
          and report["codec_sha256"] == codec_sha
          and report["context_raw_sha256"] == data["expected_catalog_context_sha256"],
          "public catalog prefix identity differs")
    _need(type(report["offered_ids"]) is list and all(type(value) is int for value in report["offered_ids"])
          and report["offered_ids"] == data["prefix_ids"], "original public prefix binding differs")
    allowed, status = report["allowed_token_ids"], report["status"]
    _need(type(allowed) is list and len(allowed) <= VOCABULARY_SIZE
          and all(type(value) is int and 0 <= value < VOCABULARY_SIZE for value in allowed)
          and allowed == sorted(set(allowed)), "bounded exact allowed-ID inventory required")
    reasons = {"prefix": {None}, "complete": {None},
        "rejected": {"invalid_token_ids", "missing_bos", "interior_special_tokens", "invalid_compact_prefix"},
        "budget_exhausted": {"output_limit_without_eos", "no_admissible_next_token_within_total_limit"}}
    _need(type(status) is str and status in reasons
          and (report["reason"] is None or type(report["reason"]) is str)
          and report["reason"] in reasons[status]
          and ((bool(allowed) and status == "prefix" and len(data["prefix_ids"]) < MAX_SEQUENCE_TOKENS)
               or (not allowed and status in {"complete", "rejected", "budget_exhausted"})),
          "public prefix disposition differs")
    _need(type(report["remaining_token_slots"]) is int
          and report["remaining_token_slots"] == MAX_SEQUENCE_TOKENS - len(data["prefix_ids"])
          and report["local_prefix_only"] is True and report["global_completability_proven"] is False,
          "public prefix budget or local-only boundary differs")
    counts = report["counts"]
    _need(type(counts) is dict and set(counts) == {"nodes", "quantifiers", "modal_nodes", "predicate_occurrences"}
          and all(type(value) is int and 0 <= value <= 512 for value in counts.values())
          and all(value <= counts["nodes"] for value in counts.values()), "public prefix counts differ")
    context = report["catalog_context"]
    _need(type(context) is dict and set(context) == {"schema", "selection_policy", "catalog"}
          and context["schema"] == "legal-relational-compact-catalog-context/v1"
          and context["selection_policy"] == "referenced_predicates_in_catalog_order/v1"
          and _wire(context, MAX_CONTEXT_BYTES) == _wire(json.loads(data["catalog_context_raw"].decode("utf-8")), MAX_CONTEXT_BYTES)
          and report["context_sha256"] == _digest(context, MAX_CONTEXT_BYTES)
          and report["catalog_sha256"] == _digest(context["catalog"], MAX_CONTEXT_BYTES),
          "complete original catalog canonical binding differs")
    _authority(report, catalog._AUTHORITY)
    _producer_rows(report, loaded, ["logic/formalization/autoencoder/legal_compact_catalog_tokens_v1.py",
                                   *[relative for relative, _ in catalog._SOURCE_SPECS]])
    return report


def _selection_report(offered, logits, prefix, data, inference_sha, loaded):
    report = _copy(offered, 2 * 1024 * 1024)
    _need(type(report) is dict and set(report) == _SELECTION_FIELDS
          and report["schema"] == "legal-compact-catalog-token-selection/v1"
          and report["profile"] == "object-relational-compact-catalog-selection/v1"
          and report["format"] == "one-step-allowed-logit-argmax/v1"
          and report["selection_policy"] == "referenced_predicates_in_catalog_order/v1"
          and report["status"] == "selected" and report["reason"] is None
          and report["prefix_status"] == prefix["status"]
          and _wire(report["prefix_report"]) == _wire(prefix)
          and report["prefix_report_sha256"] == _digest(prefix)
          and _wire(report["logits"], MAX_LOGITS_BYTES) == _wire(logits, MAX_LOGITS_BYTES)
          and report["logits_sha256"] == _digest(logits, MAX_LOGITS_BYTES), "selection original score/prefix binding differs")
    raw_id = max(range(VOCABULARY_SIZE), key=lambda index: (logits[index], -index))
    selected = max(prefix["allowed_token_ids"], key=lambda index: (logits[index], -index))
    _need(type(report["raw_argmax_token_id"]) is int and report["raw_argmax_token_id"] == raw_id
          and type(report["selected_token_id"]) is int and report["selected_token_id"] == selected
          and type(report["raw_argmax_score"]) is float and report["raw_argmax_score"] == logits[raw_id]
          and type(report["selected_score"]) is float and report["selected_score"] == logits[selected]
          and report["tie_breaker"] == "lowest_token_id"
          and report["selection_performed"] is True and type(report["tokens_appended"]) is int
          and report["tokens_appended"] == 1 and report["selection_overrode_raw_argmax"] is (raw_id != selected)
          and _wire(report["offered_prefix_ids"]) == _wire(data["prefix_ids"])
          and _wire(report["next_prefix_ids"]) == _wire([*data["prefix_ids"], selected]),
          "selection maxima, tie policy or unchanged-prefix extension differs")
    _need(report["codec_sha256"] == inference_sha
          and report["context_raw_sha256"] == data["expected_catalog_context_sha256"]
          and report["context_sha256"] == prefix["context_sha256"]
          and report["catalog_sha256"] == prefix["catalog_sha256"]
          and report["logits_origin_verified"] is False and report["head_compatibility_qualified"] is False,
          "selection catalog or independent-authority boundary differs")
    selector = loaded[2]["selection"]
    _need(_wire(report["limitations"]) == _wire(list(selector._LIMITATIONS)), "selection limitations differ")
    _authority(report, selector._AUTHORITY)
    _producer_rows(report, loaded, ["logic/formalization/autoencoder/legal_compact_catalog_selection_v1.py",
                                   *[relative for relative, _ in selector._SOURCE_SPECS]])
    return report


def score_compact_catalog_trained_v1(checkpoint, conditioning, prefix_ids, catalog_context_raw, *,
                                    expected_checkpoint_sha256, expected_catalog_context_sha256):
    """Inspect original v2 state, bridge exact codecs and score at most one step."""
    def work(data, loaded, outer_fence):
        trained, catalog, selector = (loaded[2][name] for name in ("trained", "catalog", "selection"))
        retained = []

        def keep(value, maximum):
            retained.append((value, maximum, _digest(value, maximum)))
            return value

        def fence():
            outer_fence()
            for value, maximum, digest in retained:
                _need(_digest(value, maximum) == digest, "retained cross-owner input or observation changed")

        def call(function, *args, **kwargs):
            fence()
            failure = None
            try:
                return function(*args, **kwargs)
            except BaseException as error:
                failure = error
                raise
            finally:
                try:
                    fence()
                except BaseException:
                    if failure is None:
                        raise
                    BaseException.add_note(failure, "A closing cross-owner scoring custody check also failed.")

        value = call(trained.inspect_compact_content_trained_checkpoint_v2, data["checkpoint"],
            expected_checkpoint_sha256=data["expected_checkpoint_sha256"])
        fence()
        _need(_wire(value, MAX_CHECKPOINT_BYTES) == _wire(data["checkpoint"], MAX_CHECKPOINT_BYTES),
              "public inspector substituted original checkpoint state")
        keep(value, MAX_CHECKPOINT_BYTES)
        inference = keep(call(catalog.build_compact_catalog_token_codec_v1), MAX_CODEC_BYTES)
        fence()
        training, training_sha, inference_sha, bridge = call(_bridge, value, inference, catalog)
        fence()
        keep(training, MAX_CODEC_BYTES)
        keep(bridge, MAX_CODEC_BYTES)
        options = dict(expected_context_sha256=data["expected_catalog_context_sha256"],
                       codec=inference, expected_codec_sha256=inference_sha)
        prefix = call(catalog.compact_catalog_allowed_token_ids_v1, data["prefix_ids"], data["catalog_context_raw"], **options)
        fence()
        prefix = keep(_prefix_report(prefix, data, inference_sha, loaded), 2 * 1024 * 1024)
        allowed = prefix["allowed_token_ids"]
        logits = logits_sha = selection = shape = actual_runtime = None
        numeric = [struct.unpack("!f", struct.pack("!f", float(number)))[0] for number in data["conditioning"]]
        next_prefix = list(data["prefix_ids"])
        if allowed:
            fence()
            observed = call(trained._forward, value, data["conditioning"], data["prefix_ids"])
            fence()
            observed = keep(_copy(observed, MAX_REPORT_BYTES), MAX_REPORT_BYTES)
            _need(type(observed) is dict and set(observed) == {"logits", "numeric_conditioning", "output_shape", "runtime"}
                  and _wire(observed["numeric_conditioning"]) == _wire(numeric)
                  and _wire(observed["runtime"], 32768) == _wire(value["runtime"], 32768)
                  and _wire(observed["output_shape"]) == _wire([1, len(data["prefix_ids"]), VOCABULARY_SIZE]),
                  "actual numerical conditioning, runtime or geometry differs")
            logits, shape, actual_runtime = observed["logits"], observed["output_shape"], observed["runtime"]
            _need(type(logits) is list and len(logits) == VOCABULARY_SIZE
                  and all(type(score) is float and math.isfinite(score) for score in logits),
                  "complete finite 537-score float vector required")
            logits_sha = _digest(logits, MAX_LOGITS_BYTES)
            fence()
            selection = call(selector.select_compact_catalog_token_v1, logits, data["prefix_ids"], data["catalog_context_raw"], **options)
            fence()
            selection = _selection_report(selection, logits, prefix, data, inference_sha, loaded)
            next_prefix = selection["next_prefix_ids"]
        fence()
        return dict(schema=SCHEMA, profile=PROFILE, status="scored" if allowed else "no_forward",
            reason=None if allowed else (prefix["reason"] or prefix["status"]),
            checkpoint_sha256=data["expected_checkpoint_sha256"], weights_sha256=value["weights_sha256"],
            training_checkpoint_profile=value["profile"], training_codec=training, training_codec_sha256=training_sha,
            inference_codec=inference, inference_codec_sha256=inference_sha,
            bridge=bridge, bridge_sha256=_digest(bridge, MAX_CODEC_BYTES), lexical_bridge_verified=True,
            conditioning=data["conditioning"], conditioning_sha256=_digest(data["conditioning"]), numeric_conditioning=numeric,
            prefix_ids=data["prefix_ids"], next_prefix_ids=next_prefix,
            catalog_context_raw_utf8=data["catalog_context_raw"].decode("utf-8"),
            catalog_context_raw_sha256=data["expected_catalog_context_sha256"],
            context_sha256=prefix["context_sha256"], catalog_sha256=prefix["catalog_sha256"], prefix_report=prefix,
            logits=logits, logits_sha256=logits_sha, selection=selection, output_shape=shape,
            declared_runtime=value["runtime"], actual_runtime=actual_runtime,
            runtime_verified=bool(allowed), runtime_torch_version_verified=bool(allowed),
            numerical_forward_executed=bool(allowed), model_restore_performed=bool(allowed),
            model_executed=bool(allowed), numerical_forward_count=int(bool(allowed)),
            original_forward_count=int(bool(allowed)), replay_forward_count=0, reference_forward_count=0,
            compact_training_steps=value["progress"]["optimizer_steps"], training_progress=value["progress"],
            initial_checkpoint_sha256=value["initial_checkpoint_sha256"], initial_weights_sha256=value["initial_weights_sha256"],
            parent_checkpoint_sha256=value["parent_checkpoint_sha256"],
            optimizer_state_sha256=_digest(value["optimizer_state"], MAX_CHECKPOINT_BYTES),
            optimizer_config=value["optimizer_config"], optimizer_policy=value["optimizer_policy"],
            training_population_sha256=value["population_sha256"], training_population_count=value["population_count"],
            training_executed=False, optimizer_executed=False, optimizer_constructed=False, optimizer_state_restored=False,
            catalog_training_verified=False, authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0,
            owner_pins=_pins(loaded), limitations=list(_LIMITATIONS))

    return _operation(dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids,
        catalog_context_raw=catalog_context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_catalog_context_sha256=expected_catalog_context_sha256), work)


__all__ = ["CompactCatalogTrainedScoringError", "score_compact_catalog_trained_v1"]
