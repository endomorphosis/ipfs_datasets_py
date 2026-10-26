"""An explicit vocabulary view of unchanged seeded counted28 weights.

The original head owns checkpoint validation, strict restore and GRU forward.
This adapter translates three-form lexical IDs and observes unmasked scores;
it creates no checkpoint, weights, optimizer, trainer or generation loop.
Callers must arrange the existing admitted one-thread CPU execution scope.
"""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

SCHEMA = "legal-counted-threshold-numerical-view/v2"
PROFILE = "seeded-counted28-three-form-vocabulary-view-384/v2"
SCORE_SCHEMA = "legal-counted-threshold-numerical-view-score/v2"
EVALUATION_SCHEMA = "legal-counted-threshold-numerical-view-teacher-forced/v2"
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_HOST_NAME = "ipfs_datasets_py.logic.formalization.autoencoder.legal_counted_content_head_v1"
_HOST_SHA = "b51d003f99c2cc889776509bbda165477833bb09ee327da8549bc6d17169e4e6"
_CODEC_NAME = "ipfs_datasets_py.logic.autoformal.legal_counted_threshold_codec_v2"
_CODEC_SHA = "94d6d7f722394c5344152303bc1504c545bcf9f2ef2a47b9b2d7f3360a1d0507"
_OLD_LITERAL = '"legal-counted-compact-content/v1"'
_NEW_LITERAL = '"legal-counted-threshold-content/v2"'
_AUTHORITY = dict.fromkeys((
    "source_bound", "source_semantics_verified", "conditioning_producer_verified",
    "conditioning_space_training_compatibility_verified", "permitted_inference_context_verified",
    "varied_reviewed_target_population_verified", "training_qualified", "training_gold_qualified",
    "evaluation_gold_qualified", "source_fidelity_verified", "checkpoint_compatibility_verified",
    "accepted", "admitted", "proof_authority", "Lean_admitted",
), False)
_LIMITATIONS = [
    "An explicit vocabulary view reuses unchanged seeded-v1 weights; it is not a new or newly trained checkpoint.",
    "Twenty-seven spellings are identical; one schema marker is explicitly relabeled, with no learned replacement row.",
    "The actual numeric ID mapping is identity for this exact pair of codecs; no nonidentity permutation is demonstrated.",
    "All 28 scores remain unmasked. Raw lexical prefixes need not be grammatical, and no generation loop is supplied.",
    "Three authored limits are label material, not independently reviewed statutes or a held-out training population.",
    "Conditioning is an unverified caller vector. The common cap-free signature context validates labels and never enters the GRU.",
    "Transferred snapshots require their separate donor-aware validator and are outside this seeded-only consumer.",
    "Named source checks and a recorded Torch version do not attest third-party binaries, cached bytecode or a hermetic runtime.",
]


def _modules():
    host = importlib.import_module(_HOST_NAME)
    path = _SELF_PATH.with_name("legal_counted_content_head_v1.py")
    if type(getattr(host, "__file__", None)) is not str or Path(host.__file__).absolute() != path:
        raise ValueError("canonical unchanged seeded counted28 owner required")
    base = host._base()
    base._source(path, _HOST_SHA)
    codec = importlib.import_module(_CODEC_NAME)
    codec_path = _SELF_PATH.parents[3] / "logic/autoformal/legal_counted_threshold_codec_v2.py"
    base._need(type(getattr(codec, "__file__", None)) is str
               and Path(codec.__file__).absolute() == codec_path,
               "canonical three-form codec owner required")
    pins = [base._source(_SELF_PATH, _SELF_SHA), base._source(path, _HOST_SHA),
            base._source(codec_path, _CODEC_SHA)]
    return host, codec, base, pins


def _operation(original, work, *, numeric=False):
    host, codec, base, pins = _modules()
    snapshot = base._copy(original, base.MAX_INPUT_BYTES, allow_bytes=True)
    token = base._fingerprint(snapshot)
    failure = None

    def fence():
        current_host, current_codec, current_base, current_pins = _modules()
        base._need(current_host is host and current_codec is codec and current_base is base
                   and current_pins == pins, "threshold numerical view sources or owners changed")
        base._need(base._fingerprint(base._copy(original, base.MAX_INPUT_BYTES, allow_bytes=True)) == token
                   and base._fingerprint(snapshot) == token,
                   "original or captured threshold numerical inputs changed")

    try:
        def delegate(data, loaded, offered_base, modules):
            base._need(offered_base is base, "captured numerical owner changed")
            result = work(data, loaded, base, modules, host, codec, fence)
            fence()
            return result
        return host._operation(snapshot, delegate, numeric=numeric)
    except BaseException as error:
        failure = error
        raise
    finally:
        base._finish(failure, fence)


def _view(base, modules, host, codec):
    old = modules[host._OWNER_SPECS[2][0]].build_counted_frame_token_codec_v1()
    new = codec.build_counted_threshold_token_codec_v2()
    new_sha = codec.counted_threshold_token_codec_sha256(new)
    base._need(base._digest(old) == host._CODEC_SHA, "exact original model codec required")
    old_vocabulary, new_vocabulary = old["vocabulary"], new["vocabulary"]
    base._need(len(old_vocabulary) == len(new_vocabulary) == 28
               and set(old_vocabulary) & set(new_vocabulary) == set(old_vocabulary) - {_OLD_LITERAL}
               and set(new_vocabulary) - set(old_vocabulary) == {_NEW_LITERAL},
               "exact twenty-seven shared spellings and one schema relabel required")
    positions = {token: index for index, token in enumerate(old_vocabulary)}
    rows = [dict(token_id=index, token=token,
                 model_token_id=positions[_OLD_LITERAL if token == _NEW_LITERAL else token],
                 model_token=_OLD_LITERAL if token == _NEW_LITERAL else token,
                 policy="explicit_schema_role_relabel" if token == _NEW_LITERAL else "exact_spelling")
            for index, token in enumerate(new_vocabulary)]
    mapping = [row["model_token_id"] for row in rows]
    base._need(mapping == list(range(28)), "selected codecs must retain the observed identity numeric map")
    return dict(schema=SCHEMA, profile=PROFILE, model_head_profile=host.PROFILE,
        model_codec_sha256=host._CODEC_SHA, observation_codec=new, observation_codec_sha256=new_sha,
        observation_to_model_ids=mapping, lexical_rows=rows, exact_spelling_count=27,
        explicit_schema_relabel_count=1, numeric_id_mapping_is_identity=True,
        input_dimension=384, max_total_ids=512, admissible_content_count=3,
        implementation=dict(adapter_sha256=_SELF_SHA, seeded_head_sha256=_HOST_SHA,
                            threshold_codec_sha256=_CODEC_SHA),
        checkpoint_rewritten=False, weights_modified=False, new_checkpoint_created=False,
        numerical_forward_executed=False, model_restore_performed=False,
        optimizer_executed=False, training_executed=False, counted_training_steps=0,
        generation_executed=False, native_build_executed=False,
        source_dependence_established=False,
        training_mask=0, evaluation_gold_mask=0, authority=dict(_AUTHORITY),
        limitations=list(_LIMITATIONS))


def _checked_view(data, base, modules, host, codec):
    base._hash(data["expected_view_sha256"], "exact threshold numerical vocabulary view")
    expected = _view(base, modules, host, codec)
    base._need(base._digest(data["view"]) == data["expected_view_sha256"]
               and base._wire(data["view"], base.MAX_CODEC_BYTES)
                   == base._wire(expected, base.MAX_CODEC_BYTES),
               "independently pinned exact threshold numerical view required")
    return expected


def _observation(base, value, data, numeric, view):
    return dict(schema=SCORE_SCHEMA, profile=PROFILE,
        checkpoint_sha256=data["expected_checkpoint_sha256"], checkpoint_profile=value["profile"],
        weights_sha256=value["weights_sha256"], model_codec_sha256=value["codec_sha256"],
        observation_codec_sha256=view["observation_codec_sha256"],
        view_sha256=data["expected_view_sha256"], observation_to_model_ids=view["observation_to_model_ids"],
        exact_spelling_count=27, explicit_schema_relabel_count=1, numeric_id_mapping_is_identity=True,
        conditioning=data["conditioning"], conditioning_sha256=base._digest(data["conditioning"]),
        numeric_conditioning=numeric, conditioning_role=value["input_role"],
        grammar_mask_applied=False, grammatical_prefix_verified=False,
        numerical_forward_executed=True, model_restore_performed=True,
        checkpoint_rewritten=False, weights_modified=False, new_checkpoint_created=False,
        optimizer_executed=False, training_executed=False, counted_training_steps=0,
        generation_executed=False, native_build_executed=False,
        source_dependence_established=False,
        training_mask=0, evaluation_gold_mask=0, authority=dict(_AUTHORITY),
        limitations=list(_LIMITATIONS))


def build_counted_threshold_numerical_view_v2():
    """Declare the exact vocabulary view without constructing or restoring a model."""
    return _operation({}, lambda data, loaded, base, modules, host, codec, before_forward:
                      _view(base, modules, host, codec))


def counted_threshold_numerical_view_sha256(view):
    """Accept only the exact rebuilt view, never an alternative caller mapping."""
    def work(data, loaded, base, modules, host, codec, before_forward):
        expected = _view(base, modules, host, codec)
        base._need(base._wire(data["view"], base.MAX_CODEC_BYTES)
                   == base._wire(expected, base.MAX_CODEC_BYTES), "exact threshold numerical view required")
        return base._digest(expected)
    return _operation(dict(view=view), work)


def score_counted_threshold_numerical_view_v2(checkpoint, conditioning, prefix_ids, *,
        expected_checkpoint_sha256, view, expected_view_sha256):
    """Expose all successor-ordered last-position scores from unchanged v1 weights."""
    def work(data, loaded, base, modules, host, codec, before_forward):
        selected = _checked_view(data, base, modules, host, codec)
        host._prefix(base, data["prefix_ids"])
        numeric = base._conditioning(data["conditioning"])
        value = host._checkpoint(data, base, modules)
        mapping = selected["observation_to_model_ids"]
        model_ids = [mapping[index] for index in data["prefix_ids"]]
        before_forward()
        raw = host._forward(value, numeric, model_ids, loaded, base)[-1]
        logits = [raw[index] for index in mapping]
        result = _observation(base, value, data, numeric, selected)
        result.update(prefix_ids=data["prefix_ids"], model_prefix_ids=model_ids,
            output_shape=[1, len(model_ids), 28], logits=logits, logits_sha256=base._digest(logits),
            raw_argmax_token_id=max(range(28), key=lambda index: logits[index]))
        return result
    return _operation(dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids,
        expected_checkpoint_sha256=expected_checkpoint_sha256, view=view,
        expected_view_sha256=expected_view_sha256), work, numeric=True)


def evaluate_counted_threshold_numerical_view_v2(checkpoint, conditioning, target_ids, context_raw, *,
        expected_checkpoint_sha256, expected_context_sha256, view, expected_view_sha256):
    """Decode a complete authored successor label before unmasked teacher forcing."""
    def work(data, loaded, base, modules, host, codec, before_forward):
        selected = _checked_view(data, base, modules, host, codec)
        decoded = codec.decode_counted_threshold_tokens_v2(data["target_ids"], data["context_raw"],
            expected_context_sha256=data["expected_context_sha256"],
            codec=selected["observation_codec"], expected_codec_sha256=selected["observation_codec_sha256"])
        ids = data["target_ids"]
        host._prefix(base, ids[:-1])
        numeric = base._conditioning(data["conditioning"])
        value = host._checkpoint(data, base, modules)
        mapping = selected["observation_to_model_ids"]
        model_ids = [mapping[index] for index in ids[:-1]]
        before_forward()
        raw = host._forward(value, numeric, model_ids, loaded, base)
        logits = [[row[index] for index in mapping] for row in raw]
        torch = base._torch(loaded)
        with torch.inference_mode():
            scores = torch.tensor(logits, dtype=torch.float64, device="cpu")
            labels = torch.tensor(ids[1:], dtype=torch.long, device="cpu")
            losses = torch.nn.functional.cross_entropy(scores, labels, reduction="none").tolist()
        predictions = [max(range(28), key=lambda index: row[index]) for row in logits]
        result = _observation(base, value, data, numeric, selected)
        result.update(schema=EVALUATION_SCHEMA, target_ids=ids, input_ids=ids[:-1], label_ids=ids[1:],
            model_input_ids=model_ids, output_shape=[1, len(ids)-1, 28], logits=logits,
            logits_sha256=base._digest(logits), token_losses=losses,
            mean_cross_entropy=sum(losses)/len(losses), prediction_ids=predictions,
            predicted_tokens=len(losses), eos_included_in_loss=ids[-1] == 2,
            exact_teacher_forced_token_matches=sum(a == b for a, b in zip(predictions, ids[1:])),
            exact_teacher_forced_sequence_match=predictions == ids[1:],
            context_raw_sha256=data["expected_context_sha256"],
            canonical_context_sha256=decoded["context_sha256"],
            target_context_role="label_validation_only_unreviewed_cap_free_signature",
            complete_target_decode_sha256=base._digest(decoded), decoded_maximum=decoded["decoded_maximum"],
            admissible_content_count=3, exposed_labels_in_this_evaluation=1,
            varied_reviewed_target_population_verified=False, source_dependence_established=False)
        return result
    return _operation(dict(checkpoint=checkpoint, conditioning=conditioning, target_ids=target_ids,
        context_raw=context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_context_sha256=expected_context_sha256, view=view,
        expected_view_sha256=expected_view_sha256), work, numeric=True)


__all__ = ["build_counted_threshold_numerical_view_v2", "counted_threshold_numerical_view_sha256",
           "score_counted_threshold_numerical_view_v2", "evaluate_counted_threshold_numerical_view_v2"]
