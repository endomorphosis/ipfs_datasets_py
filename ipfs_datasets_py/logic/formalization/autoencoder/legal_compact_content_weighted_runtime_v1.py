"""Explicit model-only inference for the complete weighted LegalIR checkpoint.

The weighted owner validates its own checkpoint and objective. The byte-pinned
prepared runtime supplies only its private numerical session, receiving that
intact checkpoint; no old-v2 checkpoint conversion or optimizer restoration is
performed. Grammar and token selection remain with their existing owners.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import stat

SCHEMA = "legal-weighted-content-generation/v1"
PROFILE = "bounded-weighted-compact384-model-only-generation/v1"
INSPECT_SCHEMA = "legal-weighted-content-inference-inspection/v1"
MAX_CHECKPOINT_BYTES = 16 * 1024**2
MAX_INPUT_BYTES = 24 * 1024**2
MAX_REPORT_BYTES = 8 * 1024**2
MAX_CONTEXT_BYTES = 524288
MAX_TOTAL_IDS = 512
MAX_NEW_TOKENS = 64
AUTHORITY = {key: False for key in (
    "accepted", "admitted", "source_encoder_authenticated", "source_semantics_verified",
    "context_permission_verified", "prefix_origin_verified", "heldout_accuracy",
    "statutory_accuracy", "graph_admission", "Lean_admission", "native_admission")}
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SPECS = (
    ("weighted", "logic/formalization/autoencoder/legal_compact_content_weighted_training_v1.py",
     "3646b831d73338a2bc93f4ca414f8e3cf317b576d404244be4089fbe736168cc"),
    ("prepared", "logic/formalization/autoencoder/legal_compact_content_prepared_runtime_v3.py",
     "a7d7cedfa482537ac76a9ccf9a49a79f6108e89268b02ca3b355abcfe774ec1e"),
)
_LIMITATIONS = (
    "The complete weighted checkpoint contains exposed training references; its validator reads and recomputes their grammar inventories.",
    "Only supplied conditioning and current prefix IDs enter the numerical model; validation target access is a separate observation.",
    "Conditioning, context permission and prefix origins are caller observations, not authenticated source semantics or authority.",
    "The objective policy remains checkpoint provenance; inference does not apply its loss weights to logits or token selection.",
    "Full-prefix inference is unchanged. One private model lifetime belongs to this operation; no cross-call cache or incremental hidden state exists.",
    "Raw maxima are observed along constrained prefixes, not an independently generated unconstrained trajectory.",
    "Complete local syntax and exact direct/restored numerical parity do not establish faithful statutory interpretation, heldout reconstruction or proof validity.",
    "Checkpoint lineage and historical optimizer state are validated commitments, not a replay or independent proof of past training.",
    "Terminal or blocked supplied prefixes construct no numerical model and do not establish a verified live numerical runtime.",
    "Source/input endpoint checks and private-session guards are bounded custody checks, not arbitrary-bytecode or operating-system attestation.",
)


class WeightedRuntimeError(ValueError):
    """Weighted checkpoint, inference input, source or numerical contract failed."""


def _need(ok, message):
    if not ok:
        raise WeightedRuntimeError(message)


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _source(path, expected):
    _need(path.is_absolute() and path.resolve(strict=True) == path, "unaliased canonical source required")
    before = path.lstat()
    _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 131072,
          "bounded single-link source required")
    raw = path.read_bytes()
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
    _need(identity(before) == identity(after) and len(raw) == before.st_size
          and hashlib.sha256(raw).hexdigest() == expected, "source bytes or identity changed")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}, identity(after)


def _sources():
    root = None
    for ancestor in _SELF_PATH.parents:
        for candidate in (ancestor / "ipfs_datasets_py", ancestor / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SPECS[0][1]).is_file():
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "canonical weighted/prepared owners unavailable")
    return root, [_source(_SELF_PATH, _SELF_SHA),
                  *[_source(root / relative, pin) for _, relative, pin in _SPECS]]


def _operation(original, work):
    root, observed = _sources()
    modules, loaded, weighted_sources, snapshot, token, failure = {}, None, None, None, None, None
    def fence():
        _need(_sources() == (root, observed), "weighted inference source custody changed")
        for key, relative, _ in _SPECS:
            if key in modules:
                _need(Path(modules[key].__file__).absolute() == root / relative, "loaded weighted/prepared origin changed")
        if loaded is not None:
            _need(modules["prepared"]._sources() == loaded[:2], "prepared dependency custody changed")
            for key, _, relative, _ in modules["prepared"]._SOURCE_SPECS:
                if key is not None:
                    _need(Path(loaded[2][key].__file__).absolute() == root / relative,
                          "prepared public dependency origin changed")
        if weighted_sources is not None:
            _need(modules["weighted"]._sources() == weighted_sources, "weighted checkpoint owner custody changed")
        if token is not None:
            helper = modules["prepared"]
            _need(helper._fingerprint(original, MAX_INPUT_BYTES) == token
                  and helper._fingerprint(snapshot, MAX_INPUT_BYTES) == token, "original or captured inference input changed")
    try:
        for key, relative, _ in _SPECS:
            module = importlib.import_module("ipfs_datasets_py." + relative[:-3].replace("/", "."))
            _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                  "canonical weighted/prepared import required")
            modules[key] = module
        helper = modules["prepared"]
        snapshot = helper._copy(original, MAX_INPUT_BYTES, allow_bytes=True)
        token = helper._fingerprint(snapshot, MAX_INPUT_BYTES)
        loaded = helper._owners()
        weighted_sources = modules["weighted"]._sources()
        _need(loaded[0] == weighted_sources[0] == root, "canonical dependency roots disagree")
        pins = {}
        for item, _ in observed + loaded[1] + weighted_sources[1]:
            _need(item["path"] not in pins or pins[item["path"]] == item, "duplicate source identities disagree")
            pins[item["path"]] = item
        fence()
        result = work(snapshot, modules, loaded, [pins[key] for key in sorted(pins)], fence)
        raw = helper._wire(result, MAX_REPORT_BYTES)
        fence()
        return json.loads(raw)
    except BaseException as error:
        failure = error
        if isinstance(error, ValueError) and not isinstance(error, WeightedRuntimeError):
            raise WeightedRuntimeError(str(error)) from error
        raise
    finally:
        try:
            fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing weighted inference custody check also failed.")


def _inspect(data, modules, fence):
    for key in ("expected_checkpoint_sha256", "expected_policy_sha256"):
        _sha(data[key], key)
    helper = modules["prepared"]
    value = data["checkpoint"]
    _need(type(value) is dict and helper._digest(value, MAX_CHECKPOINT_BYTES) == data["expected_checkpoint_sha256"],
          "complete typed weighted checkpoint commitment differs")
    checked = modules["weighted"].inspect(value,
        expected_checkpoint_sha256=data["expected_checkpoint_sha256"],
        expected_policy_sha256=data["expected_policy_sha256"])
    _need(checked["checkpoint_sha256"] == data["expected_checkpoint_sha256"]
          and checked["objective_policy_sha256"] == data["expected_policy_sha256"] == value["objective_policy_sha256"]
          and checked["weights_sha256"] == value["weights_sha256"]
          and checked["inventories_sha256"] == value["inventories_sha256"]
          and checked["model_constructed"] is checked["optimizer_constructed"] is checked["runtime_verified"] is False,
          "public weighted inspector binding or no-allocation contract differs")
    fence()
    return value


def _identity(value, expected, expected_policy):
    return dict(checkpoint_sha256=expected, objective_policy_sha256=expected_policy,
        objective_policy=deepcopy(value["objective_policy"]), checkpoint_schema=value["schema"],
        checkpoint_profile=value["profile"], weights_sha256=value["weights_sha256"],
        codec_sha256=value["codec_sha256"], inventories_sha256=value["inventories_sha256"],
        donor_checkpoint_sha256=value["donor_checkpoint_sha256"],
        initial_checkpoint_sha256=value["initial_checkpoint_sha256"],
        parent_checkpoint_sha256=value["parent_checkpoint_sha256"], progress=deepcopy(value["progress"]),
        historical_donor_progress=deepcopy(value["historical_parent_progress"]),
        optimizer_state_sha256=value["optimizer_state_sha256"])


def inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Inspect the intact weighted type once; construct no model or optimizer."""
    def work(data, modules, loaded, pins, fence):
        value = _inspect(data, modules, fence)
        return dict(schema=INSPECT_SCHEMA, profile=PROFILE,
            **_identity(value, data["expected_checkpoint_sha256"], data["expected_policy_sha256"]),
            checkpoint_inspection_count=1, model_restore_count=0, numerical_forward_count=0,
            model_executed=False, runtime_verified=False, training_executed=False,
            optimizer_constructed=False, optimizer_state_restored=False,
            target_access_for_checkpoint_validation=True, authority=dict(AUTHORITY),
            training_mask=0, evaluation_gold_mask=0, owner_pins=pins, limitations=list(_LIMITATIONS))
    return _operation(dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256,
                           expected_policy_sha256=expected_policy_sha256), work)


def _inputs(data, helper):
    _sha(data["expected_context_sha256"], "context")
    _need(type(data["context_raw"]) is bytes and 0 < len(data["context_raw"]) <= MAX_CONTEXT_BYTES
          and hashlib.sha256(data["context_raw"]).hexdigest() == data["expected_context_sha256"],
          "independently pinned bounded context bytes required")
    _need(type(data["conditioning"]) is list and len(data["conditioning"]) == 384
          and all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 1e8 for x in data["conditioning"]),
          "bounded plain384 conditioning vector required")
    _need(type(data["prefix_ids"]) is list and 1 <= len(data["prefix_ids"]) <= MAX_TOTAL_IDS
          and all(type(x) is int and 0 <= x < 537 for x in data["prefix_ids"]),
          "bounded nonempty token prefix required")
    _need(type(data["max_new_tokens"]) is int and 1 <= data["max_new_tokens"] <= MAX_NEW_TOKENS,
          "new-token allowance must be a plain integer in 1..64")
    _need(type(data["prefix_origin"]) is str and data["prefix_origin"] in helper.PREFIX_ORIGINS
          and (data["prefix_origin"] != "bos_seed" or data["prefix_ids"] == [1]),
          "declared supplied prefix origin differs")
    _need(type(data["context_origin"]) is str and data["context_origin"] in helper.CONTEXT_ORIGINS,
          "declared supplied context origin differs")


def generate(checkpoint, conditioning, prefix_ids, context_raw, *, expected_checkpoint_sha256,
             expected_policy_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    """Run bounded full-prefix inference with one private model-only restore."""
    original = dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids,
        context_raw=context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_context_sha256=expected_context_sha256,
        max_new_tokens=max_new_tokens, prefix_origin=prefix_origin, context_origin=context_origin)
    def work(data, modules, loaded, pins, fence):
        helper = modules["prepared"]
        _inputs(data, helper)
        value = _inspect(data, modules, fence)
        tokens, selection = loaded[2]["tokens"], loaded[2]["selection"]
        root = loaded[0]
        token_paths = {str(root / "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py"),
                       str(root / "logic/autoformal/legal_compact_content_v1.py")}
        options = dict(expected_context_sha256=data["expected_context_sha256"],
                       codec=value["codec"], expected_codec_sha256=value["codec_sha256"])
        current, emitted, trace = list(data["prefix_ids"]), [], []
        session, failure = None, None
        def guard():
            if session is None:
                fence()
            else:
                session._guard()
        def prefix_report(ids):
            guard()
            report = tokens.compact_content_allowed_token_ids_v1(ids, data["context_raw"], **options)
            helper._producer_rows(report, loaded, token_paths)
            _need(report["offered_ids"] == ids and report["context_raw_sha256"] == data["expected_context_sha256"]
                  and report["codec_sha256"] == value["codec_sha256"], "public prefix binding differs")
            guard()
            return report
        try:
            final_prefix = prefix_report(current)
            status, reason = None, None
            if final_prefix["status"] == "complete":
                status, reason = "supplied_complete", "supplied_prefix_already_complete"
            elif not final_prefix["allowed_token_ids"]:
                status, reason = "blocked", final_prefix["reason"] or final_prefix["status"]
            else:
                while len(emitted) < data["max_new_tokens"]:
                    restored = session is None
                    if restored:
                        # This unchanged numerical primitive receives the whole
                        # validated weighted value. It never calls old-v2 inspect
                        # or receives a fabricated old-format checkpoint.
                        session = helper._PreparedModel(value, data["conditioning"], loaded, fence)
                    guard()
                    observed = session.forward(current)
                    logits = observed["logits"]
                    _need(observed["runtime"] == value["runtime"]
                          and observed["output_shape"] == [1, len(current), 537]
                          and type(logits) is list and len(logits) == 537
                          and all(type(x) is float and math.isfinite(x) for x in logits),
                          "actual complete weighted-model output differs")
                    selected = selection.select_compact_content_token_v1(logits, current, data["context_raw"], **options)
                    _need(selected["selection_performed"] is True and selected["prefix_report"] == final_prefix
                          and selected["offered_prefix_ids"] == current and selected["logits"] == logits
                          and selected["logits_sha256"] == helper._digest(logits)
                          and type(selected["selected_token_id"]) is int
                          and selected["selected_token_id"] in final_prefix["allowed_token_ids"]
                          and selected["next_prefix_ids"] == current + [selected["selected_token_id"]],
                          "public selected token disagrees with bound full537 output")
                    guard()
                    trace.append(dict(prefix_ids=list(current), logits=logits, logits_sha256=helper._digest(logits),
                        selection=selected, prefix_report=final_prefix, next_prefix_ids=list(selected["next_prefix_ids"]),
                        model_restore_performed=restored, prepared_model_reused=not restored,
                        output_shape=observed["output_shape"]))
                    emitted.append(selected["selected_token_id"])
                    current = list(selected["next_prefix_ids"])
                    final_prefix = prefix_report(current)
                    if final_prefix["status"] == "complete":
                        status, reason = "complete", None
                        break
                    if not final_prefix["allowed_token_ids"]:
                        status, reason = "blocked", final_prefix["reason"] or final_prefix["status"]
                        break
                else:
                    status, reason = "step_budget_exhausted", "max_new_tokens_reached"
            guard()
            decoded = tokens.decode_compact_content_tokens_v1(current, data["context_raw"], **options)
            helper._producer_rows(decoded, loaded, token_paths)
            _need(decoded["generated_ids"] == current and decoded["context_raw_sha256"] == data["expected_context_sha256"]
                  and decoded["codec_sha256"] == value["codec_sha256"]
                  and decoded["context_sha256"] == final_prefix["context_sha256"]
                  and ((status in ("complete", "supplied_complete")) == (decoded["status"] == "valid_candidate")),
                  "final public intake disagrees with generated prefix or terminal disposition")
            guard()
            return dict(schema=SCHEMA, profile=PROFILE,
                **_identity(value, data["expected_checkpoint_sha256"], data["expected_policy_sha256"]),
                conditioning=deepcopy(data["conditioning"]), conditioning_sha256=helper._digest(data["conditioning"]),
                context_raw_sha256=data["expected_context_sha256"], context_sha256=decoded["context_sha256"],
                initial_prefix_ids=list(data["prefix_ids"]), generated_ids=current, selected_token_ids=emitted,
                prefix_origin=data["prefix_origin"], context_origin=data["context_origin"],
                trace=trace, model_restore_count=int(session is not None), numerical_forward_count=len(trace),
                checkpoint_inspection_count=1, status=status, reason=reason,
                final_prefix_report=final_prefix, final_decoding=decoded,
                settings=dict(max_new_tokens=data["max_new_tokens"], max_total_ids=MAX_TOTAL_IDS,
                    full_prefix_each_step=True, cross_call_model_cache=False, incremental_hidden_state=False),
                emitted_token_count=len(emitted), total_token_count=len(current),
                model_executed=bool(trace), runtime_verified=bool(trace), training_executed=False,
                optimizer_constructed=False, optimizer_state_restored=False,
                target_access_for_checkpoint_validation=True,
                supplied_prefix_target_access_declared=data["prefix_origin"] == "target_derived_label",
                supplied_context_target_access_declared=data["context_origin"] == "target_derived_label",
                actual_model_inputs=["conditioning_vector", "supplied_or_generated_prefix_ids"],
                authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0,
                owner_pins=pins, limitations=list(_LIMITATIONS))
        except BaseException as error:
            failure = error
            raise
        finally:
            if session is not None:
                loaded[2]["legacy_head"]._finish(failure, session.close)
    return _operation(original, work)
