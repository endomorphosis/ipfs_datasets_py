"""Donor-required counted28 snapshots using the existing numerical transfer.

The fixed537 and seeded-counted28 owners stay unchanged. This distinct profile
publicly validates its original donor, transfers real tensors through the old
kernel, and requires that donor again when validating or observing a snapshot.
No optimizer, source encoder, grammar mask or generation loop is introduced.
"""
from __future__ import annotations

import hashlib
import importlib
import math
from pathlib import Path

SCHEMA = "legal-transferred-counted-content-head-checkpoint/v1"
PROFILE = "validated537-to-counted28-content-head-384/v1"
_HOST_NAME = "ipfs_datasets_py.logic.formalization.autoencoder.legal_counted_content_head_v1"
_HOST_SHA = "b51d003f99c2cc889776509bbda165477833bb09ee327da8549bc6d17169e4e6"
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_DONOR_CONDITIONING = "caller_supplied_unverified384"
_FIELDS = set(("schema profile architecture input_dimension input_role device dtype torch_version config codec "
    "codec_sha256 spec spec_sha256 max_total_ids implementation model_state weights_sha256 donor transfer_plan "
    "transfer_plan_sha256 kernel_transfer_lineage realized_tensor_ledger lexical_row_map donor_modified "
    "optimizer_state_included fresh_optimizer_required counted_training_steps authority training_mask "
    "evaluation_gold_mask limitations").split())
_LIMITATIONS = [
    "This separate weights-only profile requires its independently pinned original public537 donor on every validation and observation.",
    "Real tensor transfer does not establish counted training: the public537 head has zero compact updates and this counted snapshot has zero counted updates.",
    "A legacy helper policy label containing trained_parent is retained verbatim; it supplies no donor training or semantic authority.",
    "The donor does not authenticate a conditioning producer. Its unverified384 declaration remains separate from the spec raw-native-GTE expectation.",
    "Donor optimizer moments, optimizer resumption, source/context permission, source fidelity and eligible statutory supervision are not supplied.",
    "All28 logits remain unmasked. One fixed exposed authored target is not a varied population or an autonomous generation/accuracy result.",
    "Named source fences and a recorded Torch version do not attest third-party binaries, cached bytecode or a hermetic operating system.",
]


def _host():
    host = importlib.import_module(_HOST_NAME)
    path = _SELF_PATH.with_name("legal_counted_content_head_v1.py")
    if type(getattr(host, "__file__", None)) is not str or Path(host.__file__).absolute() != path:
        raise ValueError("canonical unchanged seeded counted owner required")
    base = host._base()
    base._source(path, _HOST_SHA)
    return host, base


def _operation(original, work, *, numeric=True):
    host, base = _host()
    snapshot = base._copy(original, base.MAX_INPUT_BYTES, allow_bytes=True)
    token = base._fingerprint(snapshot)
    pins = [base._source(_SELF_PATH, _SELF_SHA),
            base._source(_SELF_PATH.with_name("legal_counted_content_head_v1.py"), _HOST_SHA)]
    failure = None
    def fence():
        current, current_base = _host()
        base._need(current is host and current_base is base
                   and [base._source(_SELF_PATH, _SELF_SHA),
                        base._source(_SELF_PATH.with_name("legal_counted_content_head_v1.py"), _HOST_SHA)] == pins,
                   "counted transfer adapter/host source changed")
        base._need(base._fingerprint(base._copy(original, base.MAX_INPUT_BYTES, allow_bytes=True)) == token
                   and base._fingerprint(snapshot) == token, "original counted transfer inputs changed")
    try:
        def delegate(data, loaded, offered_base, modules):
            base._need(offered_base is base, "captured fixed537 owner changed")
            transfer = None
            inner_error = None
            try:
                if numeric:
                    transfer = base._owners(numeric=True, transfer=True)
                result = work(data, loaded, base, modules, host, transfer)
                fence()
                return result
            except BaseException as error:
                inner_error = error
                raise
            finally:
                if transfer is not None:
                    base._finish(inner_error, lambda: base._closing(transfer))
        return host._operation(snapshot, delegate, numeric=numeric)
    except BaseException as error:
        failure = error
        raise
    finally:
        base._finish(failure, fence)


def _replay(donor, expected_donor, loaded, base, modules, host, transfer):
    base._hash(expected_donor, "complete original public537 donor")
    # Genuine public validation includes strict restoration, implementation,
    # ordered codec, exact float32 state and runtime Torch-version checks.
    original = base.validate_compact_content_head_v1(donor, expected_checkpoint_sha256=expected_donor)
    settings, codec, spec, spec_sha = host._metadata(base, modules, original["config"])
    profiles = modules[host._OWNER_SPECS[1][0]]
    declaration = dict(schema="legal-counted-content-head-donor-declaration/v1",
        profile=original["profile"], architecture=original["architecture"],
        input_dimension=original["input_dimension"], input_role=original["input_role"],
        geometry={name: settings[name] for name in base._SHAPE_FIELDS},
        checkpoint_sha256=expected_donor, weights_sha256=original["weights_sha256"],
        vocabulary=original["codec"]["vocabulary"],
        vocabulary_sha256=base._digest(original["codec"]["vocabulary"]),
        torch_version=original["torch_version"], conditioning_profile=_DONOR_CONDITIONING)
    plan = profiles.plan_counted_content_head_transfer_v1(spec, codec,
        expected_spec_sha256=spec_sha, expected_codec_sha256=_codec_sha(host),
        donor_declaration=declaration, config=declaration["geometry"])
    plan_sha = profiles.counted_content_head_transfer_sha256(plan)
    profiles.validate_counted_content_head_transfer_v1(plan, spec, codec,
        expected_plan_sha256=plan_sha, expected_spec_sha256=spec_sha,
        expected_codec_sha256=_codec_sha(host), donor_declaration=declaration,
        config=declaration["geometry"])
    torch = base._torch(transfer)
    rng = torch.get_rng_state().clone()
    try:
        # This is an explicit private tensor/vocabulary view, never a forged
        # native checkpoint or a call to that checkpoint's public validator.
        numerical_view = {"model_state": original["model_state"],
                          "codec": {"target_vocabulary": original["codec"]["vocabulary"]}}
        model, lineage = transfer["modules"]["transfer"]._transfer(
            numerical_view, {"target_vocabulary": codec["vocabulary"]}, settings)
        base._need(all(tensor.device.type == "cpu" and tensor.dtype == torch.float32
                       and bool(torch.isfinite(tensor).all()) for tensor in model.state_dict().values()),
                   "transferred counted state must be finite CPU float32")
        state = {name: tensor.detach().tolist() for name, tensor in model.state_dict().items()}
        host._state(base, state, spec["identity"]["tensor_shapes"])
        inherited = sorted(set(state) - set(base._LEXICAL))
        base._need(lineage["exact_inherited_tensors"] == inherited
                   and lineage["lexical_mapped_tensors"] == sorted(base._LEXICAL)
                   and lineage["random_parameters_used"] is False and lineage["parent_modified"] is False,
                   "unchanged original transfer policy differs")
        ledger = [{"parameter": name, "target_shape": spec["identity"]["tensor_shapes"][name],
            "donor_tensor_sha256": base._digest(original["model_state"][name]),
            "target_tensor_sha256": base._digest(state[name]),
            "policy": "exact_token_row_or_full_donor_row_mean" if name in base._LEXICAL else "exact_nonlexical_copy"}
            for name in sorted(state)]
        return {"schema": SCHEMA, "profile": PROFILE, "architecture": base.ARCHITECTURE,
            "input_dimension": 384, "input_role": "unverified_caller_supplied_conditioning_vector",
            "device": "cpu", "dtype": "float32", "torch_version": original["torch_version"],
            "config": settings, "codec": codec, "codec_sha256": _codec_sha(host),
            "spec": spec, "spec_sha256": spec_sha, "max_total_ids": 512,
            "implementation": {"adapter_sha256": _SELF_SHA, "seeded_counted_owner_sha256": _HOST_SHA,
                "fixed537_implementation": base._implementation()},
            "model_state": state, "weights_sha256": base._digest(state),
            "donor": {"checkpoint_sha256": expected_donor, "weights_sha256": original["weights_sha256"],
                "codec_sha256": original["codec_sha256"], "profile": original["profile"],
                "compact_training_steps": original["compact_training_steps"],
                "initialization_mode": original["initialization"]["mode"],
                "upstream_native_optimizer_steps": original["initialization"]["parent_optimizer_steps"],
                "conditioning_profile": _DONOR_CONDITIONING, "original_required_for_restore": True},
            "transfer_plan": plan, "transfer_plan_sha256": plan_sha,
            "kernel_transfer_lineage": lineage, "realized_tensor_ledger": ledger,
            "lexical_row_map": plan["lexical_row_map"], "donor_modified": False,
            "optimizer_state_included": False, "fresh_optimizer_required": True,
            "counted_training_steps": 0, "authority": dict(host._AUTHORITY),
            "training_mask": 0, "evaluation_gold_mask": 0, "limitations": list(_LIMITATIONS)}
    finally:
        base._need(torch.equal(rng, torch.get_rng_state()), "counted transfer changed ambient CPU RNG")


def _codec_sha(host):
    return host._CODEC_SHA


def _validated(data, loaded, base, modules, host, transfer):
    base._hash(data["expected_checkpoint_sha256"], "complete transferred counted snapshot")
    offered = base._copy(data["checkpoint"], base.MAX_CHECKPOINT_BYTES)
    base._need(base._digest(offered) == data["expected_checkpoint_sha256"],
               "independent transferred snapshot hash differs")
    base._need(type(offered) is dict and set(offered) == _FIELDS
               and offered["schema"] == SCHEMA and offered["profile"] == PROFILE,
               "closed distinct transferred counted checkpoint required")
    base._need(offered["optimizer_state_included"] is False and offered["fresh_optimizer_required"] is True
               and offered["donor_modified"] is False
               and type(offered["counted_training_steps"]) is int and offered["counted_training_steps"] == 0
               and type(offered["training_mask"]) is int and offered["training_mask"] == 0
               and type(offered["evaluation_gold_mask"]) is int and offered["evaluation_gold_mask"] == 0
               and offered["authority"] == host._AUTHORITY
               and all(flag is False for flag in offered["authority"].values()),
               "weights-only transfer authority and optimizer boundaries differ")
    rebuilt = _replay(data["donor_checkpoint"], data["expected_donor_sha256"], loaded, base, modules, host, transfer)
    base._need(base._wire(offered, base.MAX_CHECKPOINT_BYTES) == base._wire(rebuilt, base.MAX_CHECKPOINT_BYTES),
               "transferred snapshot differs from original donor replay")
    # Strict actual counted restoration uses the real config/spec/state view;
    # it never asserts the distinct snapshot is a seeded-v1 checkpoint.
    host._model(offered, loaded, base)
    return offered


def create_transferred_counted_content_head_v1(donor_checkpoint, *, expected_donor_sha256):
    """Validate the original public537 donor and execute its real counted transfer."""
    return _operation(dict(donor_checkpoint=donor_checkpoint, expected_donor_sha256=expected_donor_sha256),
        lambda data, loaded, base, modules, host, transfer: _replay(data["donor_checkpoint"],
            data["expected_donor_sha256"], loaded, base, modules, host, transfer))


def transferred_counted_content_head_sha256(checkpoint):
    """Hash bounded ordinary snapshot data; hashing alone does not validate it."""
    return _operation(dict(checkpoint=checkpoint),
        lambda data, loaded, base, modules, host, transfer: base._digest(data["checkpoint"]), numeric=False)


def validate_transferred_counted_content_head_v1(checkpoint, donor_checkpoint, *,
                                                expected_checkpoint_sha256, expected_donor_sha256):
    """Replay the complete original donor transfer and strictly restore its result."""
    return _operation(dict(checkpoint=checkpoint, donor_checkpoint=donor_checkpoint,
        expected_checkpoint_sha256=expected_checkpoint_sha256, expected_donor_sha256=expected_donor_sha256), _validated)


def _observation(value, data, numeric, base, host, schema):
    return {"schema": schema, "profile": PROFILE,
        "checkpoint_sha256": data["expected_checkpoint_sha256"], "weights_sha256": value["weights_sha256"],
        "donor_checkpoint_sha256": data["expected_donor_sha256"], "transfer_plan_sha256": value["transfer_plan_sha256"],
        "codec_sha256": value["codec_sha256"], "spec_sha256": value["spec_sha256"],
        "conditioning": data["conditioning"], "conditioning_sha256": base._digest(data["conditioning"]),
        "numeric_conditioning": numeric, "conditioning_role": value["input_role"],
        "numerical_forward_executed": True, "donor_required_and_publicly_validated": True,
        "grammar_mask_applied": False, "grammatical_prefix_verified": False,
        "optimizer_executed": False, "counted_training_steps": 0,
        "authority": dict(host._AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "limitations": list(_LIMITATIONS)}


def score_transferred_counted_content_head_v1(checkpoint, donor_checkpoint, conditioning, prefix_ids, *,
                                             expected_checkpoint_sha256, expected_donor_sha256):
    """Score one nonterminal prefix without a target, context or grammar mask."""
    def work(data, loaded, base, modules, host, transfer):
        numeric = base._conditioning(data["conditioning"])
        host._prefix(base, data["prefix_ids"])
        value = _validated(data, loaded, base, modules, host, transfer)
        logits = host._forward(value, numeric, data["prefix_ids"], loaded, base)[-1]
        result = _observation(value, data, numeric, base, host, "legal-transferred-counted-content-head-score/v1")
        result.update(prefix_ids=data["prefix_ids"], output_shape=[1, len(data["prefix_ids"]), 28],
            logits=logits, logits_sha256=base._digest(logits),
            raw_argmax_token_id=max(range(28), key=lambda index: logits[index]))
        return result
    return _operation(dict(checkpoint=checkpoint, donor_checkpoint=donor_checkpoint, conditioning=conditioning,
        prefix_ids=prefix_ids, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_donor_sha256=expected_donor_sha256), work)


def evaluate_transferred_counted_content_head_v1(checkpoint, donor_checkpoint, conditioning, target_ids,
                                                context_raw, *, expected_checkpoint_sha256,
                                                expected_donor_sha256, expected_context_sha256):
    """Observe complete unmasked teacher forcing, with context remaining label-only."""
    def work(data, loaded, base, modules, host, transfer):
        numeric = base._conditioning(data["conditioning"])
        # Genuine complete decoding precedes actual donor restoration/transfer
        # or the forward, so malformed labels cannot initiate numerical work.
        counted = modules[host._OWNER_SPECS[2][0]]
        codec = counted.build_counted_frame_token_codec_v1()
        decoded = counted.decode_counted_frame_tokens_v1(data["target_ids"], data["context_raw"],
            expected_context_sha256=data["expected_context_sha256"], codec=codec,
            expected_codec_sha256=_codec_sha(host))
        ids = data["target_ids"]
        host._prefix(base, ids[:-1])
        value = _validated(data, loaded, base, modules, host, transfer)
        logits = host._forward(value, numeric, ids[:-1], loaded, base)
        # Reuse standard Torch loss on the exported float32 observations in
        # float64; this is an observation, with no backward or optimizer call.
        torch = base._torch(loaded)
        with torch.inference_mode():
            scores = torch.tensor(logits, dtype=torch.float64, device="cpu")
            labels = torch.tensor(ids[1:], dtype=torch.long, device="cpu")
            losses = torch.nn.functional.cross_entropy(scores, labels, reduction="none").tolist()
        base._need(len(losses) == len(ids) - 1 and all(math.isfinite(item) for item in losses),
                   "complete finite unmasked transfer loss required")
        predictions = [max(range(28), key=lambda index: row[index]) for row in logits]
        result = _observation(value, data, numeric, base, host, "legal-transferred-counted-content-head-teacher-forced/v1")
        result.update(target_ids=ids, input_ids=ids[:-1], label_ids=ids[1:],
            context_raw_sha256=data["expected_context_sha256"], target_context_role="label_only_target_derived",
            complete_target_decode_sha256=counted.counted_frame_report_sha256(decoded),
            output_shape=[1, len(ids)-1, 28], logits=logits, logits_sha256=base._digest(logits),
            token_losses=losses, mean_cross_entropy=sum(losses)/len(losses), prediction_ids=predictions,
            predicted_tokens=len(losses), eos_included_in_loss=ids[-1] == 2,
            exact_teacher_forced_token_matches=sum(a == b for a, b in zip(predictions, ids[1:])),
            exact_teacher_forced_sequence_match=predictions == ids[1:],
            generation_executed=False, target_population_size=1)
        return result
    return _operation(dict(checkpoint=checkpoint, donor_checkpoint=donor_checkpoint, conditioning=conditioning,
        target_ids=target_ids, context_raw=context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
        expected_donor_sha256=expected_donor_sha256, expected_context_sha256=expected_context_sha256), work)


__all__ = ["create_transferred_counted_content_head_v1", "transferred_counted_content_head_sha256",
           "validate_transferred_counted_content_head_v1", "score_transferred_counted_content_head_v1",
           "evaluate_transferred_counted_content_head_v1"]
