"""Model-only scope inference for intact scope-training LegalIR checkpoints.

The new checkpoint owner validates its complete type. Existing immutable-input,
numerical-session, lexical-scope and typed-decoder owners remain unchanged.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import importlib
import math
from pathlib import Path
import stat

SCHEMA = "legal-scope-trained-content-generation/v1"
PROFILE = "bounded-scope-trained-compact384-model-only-generation/v1"
INSPECT_SCHEMA = "legal-scope-trained-content-inference-inspection/v1"
MAX_TOTAL_IDS = 512
AUTHORITY = {key: False for key in (
    "accepted", "admitted", "source_encoder_authenticated", "source_semantics_verified",
    "context_permission_verified", "prefix_origin_verified", "heldout_accuracy",
    "statutory_accuracy", "graph_admission", "Lean_admission", "native_admission")}
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SPECS = (
    ("runtime", "logic/formalization/autoencoder/legal_compact_content_weighted_runtime_v1.py",
     "1089043125980023c8979b0ae9bf05aa121c85ce7a70e0cf2891f7f67fc3f6d5"),
    ("scope", "logic/formalization/autoencoder/legal_compact_content_scope_filter_v1.py",
     "7b77e5d71012f9394ec0eb9fa05a70310644a3ed5e334f8e91904354b6a187b9"),
    ("training", "logic/formalization/autoencoder/legal_compact_content_scope_training_v1.py",
     "fb86141cd0b69fe74e43cc9460d557e890c90c07178bf9e1a62d15098552c208"),
)
_POLICY = "lexically-bound-variable-predicate-arguments/v1"
_LIMITATIONS = (
    "The complete new-schema checkpoint is validated intact, including both baseline and scope training inventories, objective and historical optimizer state; it is never relabeled as an older checkpoint.",
    "Training objective kind and weights are provenance. Both objective arms use the same scope-filtered inference policy; no training loss or objective reweighting is applied to inference logits.",
    "The validator reads exposed target references. Only the supplied conditioning and current prefix enter the numerical model; target access does not authenticate source encoding.",
    "Old-selector decisions on refined prefixes are local comparisons, not an independently generated baseline trajectory.",
    "Scope filtering rules out some impossible predicate branches; it proves neither global completability nor eventual EOS within the fixed allowance.",
    "No legal semantics, graph admission, proof execution or reconstruction generalization is established by a locally valid output.",
)


class ScopeTrainedRuntimeError(ValueError):
    """Input, immutable checkpoint, source or numerical contract failed."""


def _need(ok, message):
    if not ok:
        raise ScopeTrainedRuntimeError(message)


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
    _need(root is not None, "canonical scope-training/runtime owners unavailable")
    return root, [_source(_SELF_PATH, _SELF_SHA),
                  *[_source(root / relative, pin) for _, relative, pin in _SPECS]]


def _operation(original, work):
    root, observed = _sources()
    modules, scope_owners, training_sources, failure = {}, None, None, None

    def outer_fence():
        _need(_sources() == (root, observed), "scope inference source custody changed")
        for key, relative, _ in _SPECS:
            if key in modules:
                _need(Path(modules[key].__file__).absolute() == root / relative,
                      "loaded scope/runtime origin changed")
        if training_sources is not None:
            _need(modules["training"]._sources() == training_sources,
                  "new checkpoint owner source custody changed")
        if scope_owners is not None:
            current = modules["scope"]._owners()
            _need(current[0] is scope_owners[0] and current[1] is scope_owners[1]
                  and current[2] == scope_owners[2], "scope dependency custody changed")

    try:
        for key, relative, _ in _SPECS:
            module = importlib.import_module("ipfs_datasets_py." + relative[:-3].replace("/", "."))
            _need(type(module.__file__) is str and Path(module.__file__).absolute() == root / relative,
                  "canonical scope/runtime import required")
            modules[key] = module
        runtime, scope, training = modules["runtime"], modules["scope"], modules["training"]
        scope_owners = scope._owners()
        training_sources = training._sources()
        _need(training_sources[0] == root, "new checkpoint owner root disagrees")
        _need(scope.POLICY == _POLICY, "explicit scope policy differs")
        outer_fence()

        def wrapped(data, dependencies, loaded, pins, original_fence):
            def fence():
                original_fence()
                outer_fence()
            _need(loaded[0] == root and scope_owners[0] is loaded[2]["selection"]
                  and scope_owners[1] is loaded[2]["tokens"], "scope and numerical dependencies disagree")
            combined = {item["path"]: item for item in pins}
            for item in [row[0] for row in observed + training_sources[1]] + scope_owners[2]:
                _need(item["path"] not in combined or combined[item["path"]] == item,
                      "overlapping scope/runtime identities disagree")
                combined[item["path"]] = item
            fence()
            result = work(data, dependencies, loaded, [combined[k] for k in sorted(combined)],
                          fence, runtime, scope, training, scope_owners[2])
            fence()
            return result
        return runtime._operation(original, wrapped)
    except BaseException as error:
        failure = error
        if isinstance(error, ValueError) and not isinstance(error, ScopeTrainedRuntimeError):
            failure = ScopeTrainedRuntimeError(str(error))
            raise failure from error
        raise
    finally:
        try:
            outer_fence()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing scope inference custody check also failed.")



def _inspect(data, helper, runtime, training, fence):
    for key in ("expected_checkpoint_sha256", "expected_policy_sha256"):
        runtime._sha(data[key], key)
    value = data["checkpoint"]
    _need(type(value) is dict and value.get("schema") == training.SCHEMA
          and helper._digest(value, runtime.MAX_CHECKPOINT_BYTES) == data["expected_checkpoint_sha256"],
          "complete independently bound scope-training checkpoint required")
    checked = training.inspect(value, expected_checkpoint_sha256=data["expected_checkpoint_sha256"],
                               expected_policy_sha256=data["expected_policy_sha256"])
    _need(checked["schema"] == value["schema"] and checked["profile"] == value["profile"]
          and checked["checkpoint_sha256"] == data["expected_checkpoint_sha256"]
          and checked["objective_policy_sha256"] == data["expected_policy_sha256"] == value["objective_policy_sha256"]
          and checked["objective_kind"] == value["objective_policy"]["objective_kind"]
          and all(checked[key] == value[key] for key in (
              "weights_sha256", "optimizer_state_sha256", "inventories_sha256",
              "scope_inventories_sha256", "scope_policy_sha256", "progress", "parameter_order"))
          and checked["model_constructed"] is checked["optimizer_constructed"] is checked["runtime_verified"] is False
          and checked["authority"] and all(item is False for item in checked["authority"].values()),
          "new-schema public inspector binding or no-allocation contract differs")
    fence()
    return value


def _identity(value, data, runtime):
    result = runtime._identity(value, data["expected_checkpoint_sha256"], data["expected_policy_sha256"])
    result.update(objective_kind=value["objective_policy"]["objective_kind"],
        scope_inventories_sha256=value["scope_inventories_sha256"],
        baseline_inventories_sha256=value["inventories_sha256"],
        training_scope_policy=deepcopy(value["scope_policy"]),
        training_scope_policy_sha256=value["scope_policy_sha256"],
        checkpoint_validator_schema=value["schema"], checkpoint_schema_conversion_performed=False)
    return result


def inspect(checkpoint, *, expected_checkpoint_sha256, expected_policy_sha256):
    """Validate the intact new type without model or optimizer allocation."""
    def work(data, modules, loaded, pins, fence, runtime, scope, training, scope_pins):
        value = _inspect(data, modules["prepared"], runtime, training, fence)
        return dict(schema=INSPECT_SCHEMA, profile=PROFILE, **_identity(value, data, runtime),
            scope_policy=_POLICY, scope_owner_pins=deepcopy(scope_pins),
            checkpoint_inspection_count=1, model_restore_count=0, numerical_forward_count=0,
            model_executed=False, runtime_verified=False, training_executed=False,
            optimizer_constructed=False, optimizer_state_restored=False,
            target_access_for_checkpoint_validation=True,
            authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0,
            owner_pins=pins, limitations=list(runtime._LIMITATIONS) + list(_LIMITATIONS))
    return _operation(dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256,
                           expected_policy_sha256=expected_policy_sha256), work)


def generate(checkpoint, conditioning, prefix_ids, context_raw, *, expected_checkpoint_sha256,
             expected_policy_sha256, expected_context_sha256, max_new_tokens, prefix_origin, context_origin):
    """Run at most64 scope-selected tokens with one new-schema model-only restore."""
    original = dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids,
        context_raw=context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_context_sha256=expected_context_sha256,
        max_new_tokens=max_new_tokens, prefix_origin=prefix_origin, context_origin=context_origin)
    def work(data, modules, loaded, pins, fence, runtime, scope, training, scope_pins):
        helper = modules["prepared"]
        runtime._inputs(data, helper)
        value = _inspect(data, helper, runtime, training, fence)
        tokens = loaded[2]["tokens"]
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
        def scope_report(report, schema):
            _need(report["schema"] == schema and report["policy"] == _POLICY
                  and report["owner_pins"] == scope_pins
                  and report["authority"] and all(v is False for v in report["authority"].values())
                  and type(report["training_mask"]) is int and report["training_mask"] == 0
                  and type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0,
                  "scope producer identity or authority differs")
        def prefix_report(ids):
            guard()
            report = scope.allowed_token_ids(ids, data["context_raw"], **options)
            scope_report(report, scope.PREFIX_SCHEMA)
            helper._producer_rows(report["baseline_prefix_report"], loaded, token_paths)
            _need(set(report["allowed_token_ids"]) <= set(report["baseline_prefix_report"]["allowed_token_ids"]),
                  "scope policy expanded baseline choices")
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
                        # validated new-schema value. It never calls old-v2 inspect
                        # or receives a fabricated old-format checkpoint.
                        session = helper._PreparedModel(value, data["conditioning"], loaded, fence)
                    guard()
                    observed = session.forward(current)
                    logits = observed["logits"]
                    _need(observed["runtime"] == value["runtime"]
                          and observed["output_shape"] == [1, len(current), 537]
                          and type(logits) is list and len(logits) == 537
                          and all(type(x) is float and math.isfinite(x) for x in logits),
                          "actual complete scope-trained model output differs")
                    selected = scope.select_token(logits, current, data["context_raw"], **options)
                    scope_report(selected, scope.SELECTION_SCHEMA)
                    _need(selected["baseline_selection"]["prefix_report"] == final_prefix["baseline_prefix_report"],
                          "local baseline observation disagrees with prefix owner")
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
                **_identity(value, data, runtime),
                scope_policy=_POLICY, scope_owner_pins=deepcopy(scope_pins),
                scope_filter_source=next(deepcopy(p) for p in scope_pins if p["path"].endswith(_SPECS[1][1])),
                checkpoint_training_grammar_unchanged=True,
                local_baseline_decisions_are_independent_trajectory=False,
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
                owner_pins=pins, limitations=list(runtime._LIMITATIONS) + list(_LIMITATIONS))
        except BaseException as error:
            failure = error
            raise
        finally:
            if session is not None:
                loaded[2]["legacy_head"]._finish(failure, session.close)
    return _operation(original, work)


__all__ = ["ScopeTrainedRuntimeError", "inspect", "generate"]
