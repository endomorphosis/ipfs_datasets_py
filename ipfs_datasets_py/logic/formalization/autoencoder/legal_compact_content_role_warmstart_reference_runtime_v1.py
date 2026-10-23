"""Explicit teacher-forced diagnostic for the two intact CP128 training rows.

The existing warm-start owner validates the complete checkpoint, including its
historical targets and named Adam state. Its target/Adam-free projection and
the original prepared model lifetime are reused unchanged. This separate
diagnostic adds one full-reference observation; it neither changes the BOS
consumer nor selects tokens. It grants no source, legal or native authority.
"""
from copy import deepcopy
import hashlib
import importlib
import math
from pathlib import Path
import stat

SCORE_SCHEMA = "legal-role-warmstart-reference-scores/v1"
PROFILE = "authored384-fixed537-warmstart-two-row-reference46/v1"
REFERENCE_ORIGIN = "exposed_checkpoint_training_reference"
MAX_REFERENCE_IDS = 47
MAX_REPORT_BYTES = 16 * 1024**2
AUTHORITY = dict.fromkeys(("accepted", "admitted", "source_encoder_authenticated",
    "source_semantics_verified", "context_permission_verified", "heldout_accuracy",
    "statutory_accuracy", "graph_admission", "Lean_admission", "native_admission"), False)
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_WARMSTART_SHA = "6711203ecbc0b063afaed3a51e35940f61c05cee80f6240f937e0f394e36b771"
_PREPARED_SHA = "a7d7cedfa482537ac76a9ccf9a49a79f6108e89268b02ca3b355abcfe774ec1e"
_PACKAGE = "ipfs_datasets_py.logic.formalization.autoencoder."
_LIMITATIONS = (
    "Only the two exposed, intact checkpoint training rows are accepted; row selection is independent of the unchanged progress cursor.",
    "Reference IDs and context are label observations. All reference tokens except terminal EOS reach the model as teacher-forced prefix inputs.",
    "The complete checkpoint validator reads historical labels and Adam; the model projection excludes them, and no optimizer is constructed or restored.",
    "The full46-token numerical geometry is separate from the existing one-token BOS geometry; numerical parity requires its own qualification.",
    "Raw unmasked full537 scores are observations, without grammar masking, ranking, token selection, generation or accuracy claims.",
    "Checkpoint/input/source/state/RNG checks grant no independent context permission, source meaning, training gold or native execution authority.",
)


class ReferenceScoreError(ValueError):
    """A reference, intact checkpoint, source or observation contract differs."""


def _need(condition, message):
    if not condition:
        raise ReferenceScoreError(message)


def _owners():
    path = _SELF_PATH.with_name("legal_compact_content_role_warmstart_runtime_v1.py")
    info = path.lstat()
    _need(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode)
          and info.st_nlink == 1 and 0 < info.st_size <= 131072
          and hashlib.sha256(path.read_bytes()).hexdigest() == _WARMSTART_SHA,
          "pinned canonical warm-start BOS owner required")
    warm = importlib.import_module(_PACKAGE + path.stem)
    _need(type(warm.__file__) is str and Path(warm.__file__).absolute() == path,
          "warm-start owner origin differs")
    legacy = warm._owners()[1]
    prepared_path = _SELF_PATH.with_name("legal_compact_content_prepared_runtime_v3.py")
    observed = [legacy._source(p, pin) for p, pin in
                ((_SELF_PATH, _SELF_SHA), (path, _WARMSTART_SHA), (prepared_path, _PREPARED_SHA))]
    return warm, observed


def _operation(original, work):
    warm, observed = _owners()
    failure = None

    def outer():
        current = _owners()
        _need(current[0] is warm and current[1] == observed,
              "reference diagnostic source custody changed")

    def adapted(data, owners, modules, loaded, pins, budget_pins, fence):
        helper = owners["prepared"]
        expected = _SELF_PATH.with_name("legal_compact_content_prepared_runtime_v3.py")
        _need(type(helper.__file__) is str and Path(helper.__file__).absolute() == expected,
              "original prepared numerical owner origin differs")
        merged = {row["path"]: row for row in pins}
        for row in [item[0] for item in observed]:
            _need(row["path"] not in merged or merged[row["path"]] == row,
                  "overlapping reference diagnostic source pins disagree")
            merged[row["path"]] = row

        def guarded():
            fence()
            outer()

        guarded()
        result = work(data, dict(owners, reference_warmstart=warm), modules, loaded,
                      [merged[key] for key in sorted(merged)], guarded)
        helper._wire(result, MAX_REPORT_BYTES)
        guarded()
        # The enclosing original operation performs its own detached JSON return.
        return helper._copy(result, MAX_REPORT_BYTES)

    try:
        return warm._operation(original, adapted)
    except BaseException as error:
        failure = error
        if isinstance(error, ValueError) and not isinstance(error, ReferenceScoreError):
            failure = ReferenceScoreError(str(error))
            raise failure from error
        raise
    finally:
        try:
            outer()
        except BaseException:
            if failure is None:
                raise
            BaseException.add_note(failure, "A closing reference diagnostic source check also failed.")


def _checked(data, owners, modules, fence):
    return owners["reference_warmstart"]._checked(data, owners, modules, fence)


def _inputs(data, helper, role, legacy):
    reference = data["reference_ids"]
    _need(type(reference) is list and len(reference) == MAX_REFERENCE_IDS
          and all(type(token) is int and 0 <= token < 537 for token in reference)
          and reference[0] == 1 and reference[-1] == 2
          and 1 not in reference[1:] and 2 not in reference[:-1],
          "exact47-ID BOS/EOS-framed reference required")
    role._sha(data["expected_reference_sha256"], "reference")
    _need(helper._digest(reference) == data["expected_reference_sha256"],
          "independently pinned reference IDs differ")
    _need(type(data["row_index"]) is int and data["row_index"] in (0, 1),
          "explicit plain checkpoint row index0 or1 required")
    legacy._inputs(dict(data, prefixes_ids=[reference[:-1]],
                        prefix_origin="target_derived_label"), helper, role)


def _bound_row(value, data, helper):
    parent = value["warmstart_parent_checkpoint"]
    rows = parent["basis_checkpoint"]["rows_utf8"]
    inventories = parent["role_inventories"]
    _need(type(rows) is list and len(rows) == 2
          and type(inventories) is list and len(inventories) == 2,
          "unchanged two-row checkpoint population required")
    index = data["row_index"]
    row, inventory = rows[index], inventories[index]
    _need(row["context_utf8"].encode("utf-8") == data["context_raw"]
          and helper._wire(row["conditioning"]) == helper._wire(data["conditioning"])
          and inventory["target_ids"] == data["reference_ids"],
          "reference/context/conditioning do not match the selected original checkpoint row")
    return row


def _reference_session_class(prepared):
    """Add one observation method; inherit original restore, guard and close."""
    class ReferencePreparedModel(prepared._PreparedModel):
        def forward_reference(self, prefix_ids):
            failure = None
            try:
                self._guard()
                with self.torch.inference_mode():
                    prefix = self.torch.tensor([prefix_ids], dtype=self.torch.long, device="cpu")
                    projected, logits = self.model(self.vector, prefix)
                    shape = [1, len(prefix_ids), 537]
                    _need(list(logits.shape) == shape and list(projected.shape) == [1, 384]
                          and logits.dtype == self.torch.float32 and logits.device.type == "cpu"
                          and projected.dtype == self.torch.float32 and projected.device.type == "cpu"
                          and bool(self.torch.isfinite(logits).all())
                          and bool(self.torch.isfinite(projected).all()),
                          "reference forward geometry, dtype, device or finite values differ")
                    scores = logits.detach().tolist()
                self._guard()
                return dict(logits=scores, numeric_conditioning=list(self.numeric_conditioning),
                            output_shape=shape, runtime=dict(self.runtime))
            except BaseException as error:
                failure = error
                raise
            finally:
                self.head._finish(failure, self._guard)

    return ReferencePreparedModel


def _matrix(observed, value, data, loaded):
    scores = observed["logits"]
    _need(observed["runtime"] == value["runtime"] and observed["output_shape"] == [1, 46, 537]
          and observed["numeric_conditioning"] == loaded[2]["legacy_head"]._conditioning(data["conditioning"])
          and type(scores) is list and len(scores) == 1
          and type(scores[0]) is list and len(scores[0]) == 46
          and all(type(row) is list and len(row) == 537
                  and all(type(number) is float and math.isfinite(number) for number in row)
                  for row in scores[0]),
          "complete finite raw1x46x537 reference matrix required")
    return scores


def score_reference(checkpoint, conditioning, reference_ids, context_raw, *,
                    expected_checkpoint_sha256, expected_policy_sha256,
                    expected_context_sha256, expected_reference_sha256, row_index, context_origin):
    """Observe one original reference with one restore/forward and no selection.

    The independent row selector does not modify or follow training progress.
    Only the exact original47-ID reference and its committed context and vector
    are accepted. The public result includes every raw score, including scores
    for syntactically ineligible tokens. No reusable model session escapes.
    """
    original = dict(checkpoint=checkpoint, conditioning=conditioning, reference_ids=reference_ids,
        context_raw=context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_context_sha256=expected_context_sha256,
        expected_reference_sha256=expected_reference_sha256, row_index=row_index,
        context_origin=context_origin)

    def work(data, owners, modules, loaded, pins, fence):
        helper, warm = owners["prepared"], owners["reference_warmstart"]
        legacy = warm._owners()[1]
        _inputs(data, helper, owners["role"], legacy)
        value = _checked(data, owners, modules, fence)
        row = _bound_row(value, data, helper)
        view = warm._serving(value, data)
        fingerprint, view_sha = helper._fingerprint(view), helper._digest(view)
        prefix = list(data["reference_ids"][:-1])
        prefix_sha = helper._digest(prefix)
        session, failure = None, None

        def serving_fence():
            fence()
            _need(helper._fingerprint(view) == fingerprint,
                  "target/Adam-free reference serving view changed")
            _need(helper._digest(prefix) == prefix_sha,
                  "captured reference prefix changed")

        def guard():
            serving_fence()
            if session is not None:
                session._guard()

        try:
            guard()
            session = _reference_session_class(helper)(view, data["conditioning"], loaded, serving_fence)
            guard()
            observed = session.forward_reference(prefix)
            guard()
            scores = _matrix(observed, value, data, loaded)
            result = dict(schema=SCORE_SCHEMA, profile=PROFILE, **warm._identity(value, data),
                serving_view_schema=warm.SERVING_SCHEMA, serving_view_sha256=view_sha,
                serving_view_fields=sorted(view), serving_view_contains_training_targets=False,
                serving_view_contains_optimizer_state=False, row_index=data["row_index"], row_id=row["id"],
                row_matches_original_checkpoint=True, progress_cursor_used_for_selection=False,
                conditioning_sha256=helper._digest(data["conditioning"]),
                context_raw_sha256=data["expected_context_sha256"], context_origin=data["context_origin"],
                reference_ids=list(data["reference_ids"]), reference_sha256=data["expected_reference_sha256"],
                reference_origin=REFERENCE_ORIGIN, reference_prefix_ids=prefix,
                reference_prefix_sha256=prefix_sha, label_ids=list(data["reference_ids"][1:]),
                logits=scores, logits_sha256=helper._digest(scores), output_shape=[1, 46, 537],
                status="scored", checkpoint_inspection_count=1, model_restore_count=1,
                numerical_forward_count=1, model_executed=True, runtime_verified=True,
                optimizer_constructed=False, optimizer_state_restored=False, training_executed=False,
                backward_performed=False, token_selection_performed=False, generation_performed=False,
                target_access_for_checkpoint_validation=True, supplied_reference_target_access_declared=True,
                supplied_context_target_access_declared=data["context_origin"] == "target_derived_label",
                actual_model_inputs=["conditioning_vector", "reference_ids_without_terminal_EOS"],
                settings=dict(reference_ids=47, teacher_prefix_ids=46, vocabulary=537,
                    BOS=1, EOS=2, raw_unmasked_scores=True, full_prefix_once=True,
                    cross_call_model_cache=False, incremental_hidden_state=False),
                owner_pins=pins, authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0,
                limitations=list(_LIMITATIONS))
            guard()
            return helper._copy(result, MAX_REPORT_BYTES)
        except BaseException as error:
            failure = error
            raise
        finally:
            if session is not None:
                loaded[2]["legacy_head"]._finish(failure, session.close)

    return _operation(original, work)


__all__ = ["ReferenceScoreError", "score_reference"]
