"""Private dual-donor initialization for a 768-input logic decoder.

All inherited decoder tensors are copied. New interfaces remain unaligned.
The 8D auxiliary branch receives the primary student's shared condition, so
its future loss can teach the shared student even with inherited heads frozen.
Import and inspection are dependency-free; numerical operations are CPU-only.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

SCHEMA = "gte-dual-donor-decoder-warm-start/v1"
ARCHITECTURE = "factorized-768-shared-condition-dual-decoder/v1"
MAX_BYTES = 64 * 1024 * 1024
PIN_FIELDS = {"teacher384_checkpoint_sha256", "teacher384_weights_sha256", "teacher384_codec_sha256",
              "legacy8_checkpoint_sha256", "legacy8_weights_sha256", "legacy8_codec_sha256"}
FLAGS = {"decoder_parameters_random": False, "boundary_alignment_required": True,
         "encoder_initially_frozen": True, "encoder_numerics_verified": False,
         "training_executed": False, "distillation_executed": False,
         "source_fidelity_qualified": False, "proof_authority": False,
         "optimizer_resume_supported": False}


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_decoder_reuse_" + name,
                                                Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PRIMARY = _helper("gte_decoder_warm_start")
_LEGACY = _helper("gte_legacy8_decoder_donor")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _pins(pins):
    _require(type(pins) is dict and set(pins) == PIN_FIELDS, "closed external donor pins required")
    _require(all(type(value) is str and re.fullmatch("[0-9a-f]{64}", value)
                 for value in pins.values()), "lowercase donor SHA256 pins required")


def _implementation():
    return {name + ".py": hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
            for name in ("gte_decoder_reuse", "gte_decoder_warm_start", "gte_legacy8_decoder_donor")}


def _identity(bundle):
    return "legal_ir:dual_donor_768_decoder:" + digest({key: bundle[key] for key in
        ("architecture", "source_profile_id", "seed", "donor_pins", "primary_sha256",
         "legacy8_sha256", "connector_sha256")})


def inspect_dual_decoder(bundle, *, expected_donor_pins):
    """Check a byte-authenticated initialization payload against external donors.

    The caller must authenticate complete saved bundle bytes before this call.
    This API accepts initialization checkpoints, not later fitted generations.
    """
    _pins(expected_donor_pins)
    fields = {"schema", "architecture", "domain_id", "dimension", "source_profile_id", "seed",
              "donor_pins", "primary", "primary_sha256", "legacy8", "legacy8_sha256",
              "connector", "connector_sha256", "representation_id", "loss_contract", "optimizer",
              "implementation", *FLAGS}
    _require(type(bundle) is dict and set(bundle) == fields, "closed dual-donor bundle required")
    _require(bundle["schema"] == SCHEMA and bundle["architecture"] == ARCHITECTURE,
             "dual-donor schema or architecture differs")
    _require(bundle["domain_id"] == "legal_ir" and type(bundle["dimension"]) is int
             and bundle["dimension"] == 768 and bundle["source_profile_id"] == _PRIMARY.PROFILE_ID,
             "dual-donor geometry or profile differs")
    _require(type(bundle["seed"]) is int and 0 <= bundle["seed"] < 2**31, "invalid connector seed")
    _require(all(type(bundle[key]) is bool and bundle[key] == value for key, value in FLAGS.items()),
             "initialization cannot claim training, alignment, qualification or resume")
    _require(bundle["donor_pins"] == expected_donor_pins, "external donor identities differ")
    _require(bundle["implementation"] == _implementation(), "dual-donor implementation differs")
    _require(digest(bundle["optimizer"]) == digest({"mode": "fresh", "state": None, "resume": False}),
             "fresh optimizer without donor moments required")
    pins = expected_donor_pins
    primary = _PRIMARY.inspect_warm_start(bundle["primary"],
        expected_teacher_sha256=pins["teacher384_checkpoint_sha256"], expected_domain_id="legal_ir",
        expected_codec_sha256=pins["teacher384_codec_sha256"])
    _require(bundle["seed"] == bundle["primary"]["seed"], "primary and connector initialization seeds differ")
    _require(bundle["primary"]["donor"]["weights_sha256"] == pins["teacher384_weights_sha256"]
             and bundle["primary"]["freeze_inherited"] is True, "exact frozen primary donor required")
    legacy_report = _LEGACY.inspect_legacy8_decoder_snapshot(bundle["legacy8"],
        expected_source_checkpoint_sha256=pins["legacy8_checkpoint_sha256"],
        expected_source_model_state_sha256=pins["legacy8_weights_sha256"])
    _require(bundle["legacy8"]["source_codec_sha256"] == pins["legacy8_codec_sha256"],
             "external legacy vocabulary differs")
    _require(bundle["primary_sha256"] == digest(bundle["primary"])
             and bundle["legacy8_sha256"] == digest(bundle["legacy8"]), "nested decoder digest differs")
    hidden = bundle["primary"]["config"]["hidden_size"]
    connector = bundle["connector"]
    _require(type(connector) is dict and set(connector) == {"weight", "bias"}, "closed connector state required")
    _LEGACY._tensor(connector["weight"], [8, hidden], "connector weight")
    _LEGACY._tensor(connector["bias"], [8], "connector bias")
    _require(bundle["connector_sha256"] == digest(connector), "connector digest differs")
    _require(digest(bundle["loss_contract"]) == digest({"primary_head": "typed_json_384_codec",
        "auxiliary_head": "typed_deontic_rule_8_codec", "shared_condition_width": hidden,
        "auxiliary_input_width": 8, "separate_vocabularies": True, "merge_logits": False,
        "reference_prefix_required_for_kd": True, "qualified_teacher_scope_required_for_kd": True}),
        "separate-head supervision contract differs")
    _require(bundle["representation_id"] == _identity(bundle), "dual-donor representation differs")
    _require(len(json.dumps(bundle, allow_nan=False)) <= MAX_BYTES, "dual-donor bundle exceeds bound")
    legacy_count = legacy_report["parameter_count"]
    return {"schema": "gte-dual-donor-decoder-inspection/v1", "status": "initialized",
        "dimension": 768, "representation_id": bundle["representation_id"],
        "primary_copied_tensor_count": primary["copied_tensor_count"],
        "primary_copied_parameter_count": primary["copied_parameter_count"],
        "legacy8_copied_tensor_count": legacy_report["tensor_count"], "legacy8_copied_parameter_count": legacy_count,
        "copied_parameter_count": primary["copied_parameter_count"] + legacy_count,
        "new_boundary_parameter_count": primary["new_boundary_parameter_count"],
        "new_auxiliary_connector_parameter_count": 8 * hidden + 8,
        "primary_max_target_tokens": bundle["primary"]["config"]["max_target_tokens"],
        "auxiliary_max_target_tokens": bundle["legacy8"]["config"]["max_target_tokens"],
        "primary_vocabulary_size": len(bundle["primary"]["codec"]["target_vocabulary"]),
        "auxiliary_vocabulary_size": len(bundle["legacy8"]["codec"]["target_vocabulary"]), **FLAGS}


def _model(primary, legacy, connector_state, seed, *, legacy_max_tokens):
    import torch
    hidden = primary.decoder.hidden_size

    class DualDonorStudent(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.primary = primary
            self.legacy8 = legacy
            self.auxiliary_connector = torch.nn.Linear(hidden, 8, device="cpu", dtype=torch.float32)

        def forward(self, vectors768, primary_prefix, auxiliary_prefix):
            shared = self.primary.condition_from_input(vectors768)
            primary_logits = self.primary.decode_from_condition(shared, primary_prefix)
            _require(isinstance(auxiliary_prefix, torch.Tensor) and auxiliary_prefix.device.type == "cpu"
                and auxiliary_prefix.dtype == torch.int64 and auxiliary_prefix.ndim == 2
                and auxiliary_prefix.shape[0] == shared.shape[0]
                and 1 <= auxiliary_prefix.shape[1] <= legacy_max_tokens
                and bool(((auxiliary_prefix >= 0)
                    & (auxiliary_prefix < self.legacy8.target_embedding.num_embeddings)).all()),
                "bounded auxiliary prefix within its independent vocabulary required")
            auxiliary_latent = self.auxiliary_connector(shared)
            _, auxiliary_logits = self.legacy8(auxiliary_latent, auxiliary_prefix)
            _require(bool(torch.isfinite(auxiliary_latent).all()) and bool(torch.isfinite(auxiliary_logits).all()),
                     "nonfinite auxiliary output")
            return {"primary_logits": primary_logits, "auxiliary_logits": auxiliary_logits,
                    "shared_condition": shared, "auxiliary_latent": auxiliary_latent}

    with torch.random.fork_rng(devices=[]):
        model = DualDonorStudent()
    if connector_state is None:
        generator = torch.Generator(device="cpu").manual_seed(seed)
        bound = 1 / math.sqrt(hidden)
        with torch.no_grad():
            for parameter in model.auxiliary_connector.parameters():
                parameter.uniform_(-bound, bound, generator=generator)
    else:
        tensors = {key: torch.tensor(value, device="cpu", dtype=torch.float32)
                   for key, value in connector_state.items()}
        _require(digest({key: value.tolist() for key, value in tensors.items()}) == digest(connector_state),
                 "connector must serialize exact float32 values")
        model.auxiliary_connector.load_state_dict(tensors, strict=True)
    return model.eval()


def create_dual_decoder(teacher384_path, legacy8_path, *, expected_teacher384_sha256,
                        expected_legacy8_sha256, repository_root=None, legacy_implementation_root=None,
                        seed=1729, bridge_checkpoint_path=None, expected_bridge_sha256=None):
    """Copy both learned heads and initialize only explicit new interfaces."""
    _require(type(seed) is int and 0 <= seed < 2**31, "invalid connector seed")
    primary, primary_checkpoint = _PRIMARY.create_warm_start(teacher384_path,
        expected_teacher_sha256=expected_teacher384_sha256, repository_root=repository_root,
        seed=seed, freeze_inherited=True, bridge_checkpoint_path=bridge_checkpoint_path,
        expected_bridge_sha256=expected_bridge_sha256)
    port = _LEGACY.load_private_legacy8_decoder(legacy8_path, expected_sha256=expected_legacy8_sha256,
                                              implementation_root=legacy_implementation_root)
    model = _model(primary, port["model"], None, seed,
                   legacy_max_tokens=port["snapshot"]["config"]["max_target_tokens"])
    connector = {key: value.detach().tolist() for key, value in model.auxiliary_connector.state_dict().items()}
    pins = {"teacher384_checkpoint_sha256": expected_teacher384_sha256,
        "teacher384_weights_sha256": primary_checkpoint["donor"]["weights_sha256"],
        "teacher384_codec_sha256": primary_checkpoint["codec_sha256"],
        "legacy8_checkpoint_sha256": expected_legacy8_sha256,
        "legacy8_weights_sha256": port["snapshot"]["source_model_state_sha256"],
        "legacy8_codec_sha256": port["snapshot"]["source_codec_sha256"]}
    bundle = {"schema": SCHEMA, "architecture": ARCHITECTURE, "domain_id": "legal_ir", "dimension": 768,
        "source_profile_id": _PRIMARY.PROFILE_ID, "seed": seed, "donor_pins": pins,
        "primary": primary_checkpoint, "primary_sha256": digest(primary_checkpoint),
        "legacy8": port["snapshot"], "legacy8_sha256": digest(port["snapshot"]),
        "connector": connector, "connector_sha256": digest(connector),
        "loss_contract": {"primary_head": "typed_json_384_codec", "auxiliary_head": "typed_deontic_rule_8_codec",
            "shared_condition_width": primary.decoder.hidden_size, "auxiliary_input_width": 8,
            "separate_vocabularies": True, "merge_logits": False,
            "reference_prefix_required_for_kd": True, "qualified_teacher_scope_required_for_kd": True},
        "optimizer": {"mode": "fresh", "state": None, "resume": False},
        "implementation": _implementation(), **FLAGS}
    bundle["representation_id"] = _identity(bundle)
    inspect_dual_decoder(bundle, expected_donor_pins=pins)
    return model, deepcopy(bundle)


def load_dual_decoder(bundle, *, expected_donor_pins):
    """Reload private CPU tensors without loading either historical optimizer."""
    bundle, expected_donor_pins = deepcopy(bundle), deepcopy(expected_donor_pins)
    inspect_dual_decoder(bundle, expected_donor_pins=expected_donor_pins)
    primary = _PRIMARY.load_warm_start(bundle["primary"],
        expected_teacher_sha256=expected_donor_pins["teacher384_checkpoint_sha256"],
        expected_domain_id="legal_ir", expected_codec_sha256=expected_donor_pins["teacher384_codec_sha256"])
    legacy = _LEGACY.load_private_legacy8_decoder_snapshot(bundle["legacy8"],
        expected_source_checkpoint_sha256=expected_donor_pins["legacy8_checkpoint_sha256"],
        expected_source_model_state_sha256=expected_donor_pins["legacy8_weights_sha256"])
    return _model(primary, legacy["model"], bundle["connector"], bundle["seed"],
                   legacy_max_tokens=bundle["legacy8"]["config"]["max_target_tokens"])


__all__ = ["create_dual_decoder", "inspect_dual_decoder", "load_dual_decoder", "digest", "SCHEMA"]
