"""Reference-trained interfaces over an authenticated affine-aligned generation.

This distinct format binds the unchanged original decoder initialization, the
complete aligned start, its external four-file pins, and a ready native plan.
Only four trained interface tensors are stored. The 26 inherited learned tensors
are reconstructed unchanged from the original initialization. Inspection uses
the standard library; callers authenticate raw file bytes separately.

The older report validator is reused only through an ephemeral compatibility
view for its loss, gradient, output and tensor arithmetic. That view is never
returned, written, or accepted as an original-start training report. All exported
identities and before-state hashes describe the authenticated aligned start.
Content consistency alone does not authenticate optimizer or embedding producer
execution, qualify either donor, authorize KD, or support optimizer resume.
"""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path


SCHEMA = "gte-aligned-interface-checkpoint/v1"
REPORT_SCHEMA = "gte-aligned-interface-training-report/v1"
PRIMARY_START = "authenticated_aligned_generation"


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_aligned_interface_checkpoint_" + name,
                                                Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load aligned interface checkpoint dependency")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _helper("gte_decoder_interface_checkpoint")
ARCHITECTURE = _BASE.ARCHITECTURE
MAX_BYTES = _BASE.MAX_BYTES
INTERFACES = _BASE.INTERFACES
HEADS = _BASE.HEADS
FLAGS = deepcopy(_BASE.FLAGS)
PROFILE = deepcopy(_BASE.PROFILE)
MODE_POLICY = deepcopy(_BASE.MODE_POLICY)
OPTIMIZER_POLICY = deepcopy(_BASE.OPTIMIZER_POLICY)
_REPORT_START_FIELDS = {"start_representation_id", "start_checkpoint_content_sha256",
                       "start_model_state_sha256", "alignment_file_pins"}
_REPORT_FIELDS = _BASE._REPORT_FIELDS | _REPORT_START_FIELDS
_ALIGNED_FIELDS = {"aligned_checkpoint_content_sha256", "aligned_representation_id",
                  "aligned_start_model_state_sha256", "alignment_file_pins",
                  "aligned_handoff_sha256", "aligned_parent_file_pins"}
_FIELDS = _BASE._FIELDS | _ALIGNED_FIELDS
_IMPLEMENTATION_NAMES = (*_BASE._IMPLEMENTATION_NAMES,
                        "gte_aligned_interface_checkpoint", "gte_aligned_interface_training")
_require = _BASE._require
_closed = _BASE._closed
_raw = _BASE._raw
_same = _BASE._same
_tensor = _BASE._tensor
_state = _BASE._state
digest = _BASE.digest


def _implementation():
    return {name + ".py": hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
            for name in _IMPLEMENTATION_NAMES}


def _parents(initialization, plan, pins, *, aligned_checkpoint, expected_alignment_file_pins):
    """Admit both generations; return the actual aligned 30-tensor start."""
    original_state, shapes = _BASE._parents(initialization, plan, pins)
    aligned = _helper("gte_aligned_decoder")
    receipt = aligned.inspect_aligned_decoder(aligned_checkpoint,
        expected_file_pins=expected_alignment_file_pins, expected_donor_pins=pins)
    _same(aligned_checkpoint["initialization"], initialization,
          "aligned checkpoint must contain the exact original initialization")
    _same(aligned_checkpoint["donor_pins"], pins, "aligned original donor pins differ")
    _same(aligned_checkpoint["parent_file_pins"], expected_alignment_file_pins,
          "aligned external parent pins differ")
    _require(receipt["initialization_representation_id"] == initialization["representation_id"]
             and aligned_checkpoint["source_profile_id"] == plan["profile_id"]
             and aligned_checkpoint["handoff"]["source_profile_id"] == plan["profile_id"]
             and aligned_checkpoint["plan"]["asset_manifest_sha256"] == plan["asset_manifest_sha256"],
             "aligned start and native producer profile or original identity differ")
    state = aligned._state(initialization, aligned_checkpoint["bridge"])
    _require(set(state) == set(shapes) and len(state) == 30,
             "thirty authenticated aligned start tensors required")
    for name, shape in shapes.items():
        _tensor(state[name], shape, name)
        if name not in INTERFACES:
            _same(state[name], original_state[name], "aligned learned decoder tensor differs")
    _require(digest(state) == aligned_checkpoint["model_state_sha256"],
             "authenticated aligned start model state differs")
    return state, shapes


def _report(report, initialization, plan, pins, interfaces, initial_state, shapes, *,
            aligned_checkpoint, expected_alignment_file_pins):
    _closed(report, _REPORT_FIELDS, "aligned interface training report")
    _require(report["schema"] == REPORT_SCHEMA and report["primary_start"] == PRIMARY_START,
             "explicit authenticated aligned-start training report required")
    _require(report["start_representation_id"] == aligned_checkpoint["representation_id"]
             and report["start_checkpoint_content_sha256"] == digest(aligned_checkpoint)
             and report["start_model_state_sha256"] == aligned_checkpoint["model_state_sha256"],
             "aligned training report start bindings differ")
    _same(report["alignment_file_pins"], expected_alignment_file_pins,
          "aligned training report external parent pins differ")
    _same(report["implementation"], _implementation(), "aligned training implementation differs")
    # This private view adapts only the historical validator's schema envelope.
    # Its actual before-state argument remains the authenticated aligned state.
    arithmetic_view = {key: deepcopy(value) for key, value in report.items()
                       if key not in _REPORT_START_FIELDS}
    arithmetic_view["schema"] = _BASE.REPORT_SCHEMA
    arithmetic_view["primary_start"] = "original_initialization"
    arithmetic_view["implementation"] = _BASE._implementation()
    _BASE._report(arithmetic_view, initialization, plan, pins, interfaces, initial_state, shapes)


def _identity(checkpoint):
    keys = ("schema", "initialization_representation_id", "initialization_content_sha256",
        "aligned_checkpoint_content_sha256", "aligned_representation_id", "aligned_start_model_state_sha256",
        "alignment_file_pins", "aligned_handoff_sha256", "aligned_parent_file_pins", "primary_start",
        "plan_sha256", "batch_sha256", "replay_sha256", "donor_pins", "profile_id", "asset_manifest_sha256",
        "codec_sha256", "interface_state_sha256", "inherited_state_sha256", "model_state_sha256",
        "training_report_sha256", "implementation", "optimizer_steps")
    return "gte-768-aligned-reference-interfaces:sha256:" + digest({key: checkpoint[key] for key in keys})


def create_interface_checkpoint(initialization, plan, *, aligned_checkpoint,
                                expected_alignment_file_pins, expected_donor_pins,
                                interfaces, training_report):
    """Construct a distinct trained generation over an admitted aligned start.

    Complete native batch/replay admission is performed by the independent
    inspector and must precede publication or loading.
    """
    initial_state, shapes = _parents(initialization, plan, expected_donor_pins,
        aligned_checkpoint=aligned_checkpoint, expected_alignment_file_pins=expected_alignment_file_pins)
    _closed(interfaces, INTERFACES, "four aligned trained interface tensors")
    for name in INTERFACES:
        _tensor(interfaces[name], shapes[name], name)
    _report(training_report, initialization, plan, expected_donor_pins, interfaces, initial_state, shapes,
        aligned_checkpoint=aligned_checkpoint, expected_alignment_file_pins=expected_alignment_file_pins)
    state = _state(initialization, interfaces)
    inherited = {name: value for name, value in initial_state.items() if name not in INTERFACES}
    inventory = _BASE._inventory(state, shapes)
    result = {"schema": SCHEMA, "architecture": ARCHITECTURE, "domain_id": "legal_ir", "dimension": 768,
        "initialization_representation_id": initialization["representation_id"],
        "initialization_content_sha256": digest(initialization),
        "aligned_checkpoint_content_sha256": digest(aligned_checkpoint),
        "aligned_representation_id": aligned_checkpoint["representation_id"],
        "aligned_start_model_state_sha256": aligned_checkpoint["model_state_sha256"],
        "alignment_file_pins": deepcopy(expected_alignment_file_pins),
        "aligned_handoff_sha256": aligned_checkpoint["handoff_sha256"],
        "aligned_parent_file_pins": deepcopy(aligned_checkpoint["parent_file_pins"]),
        "plan_sha256": plan["plan_sha256"], "batch_sha256": plan["batch_sha256"],
        "replay_sha256": plan["replay_sha256"], "donor_pins": deepcopy(expected_donor_pins),
        "profile_id": plan["profile_id"], "asset_manifest_sha256": plan["asset_manifest_sha256"],
        "codec_sha256": {name: plan["heads"][name]["codec_sha256"] for name in HEADS},
        "primary_start": PRIMARY_START, "trainable_tensor_names": list(INTERFACES),
        "interfaces": deepcopy(interfaces), "interface_state_sha256": digest(interfaces),
        "inherited_state_sha256": digest(inherited), "model_state_sha256": digest(state),
        "tensor_inventory": inventory, "tensor_inventory_sha256": digest(inventory),
        "training_report": deepcopy(training_report), "training_report_sha256": digest(training_report),
        "implementation": _implementation(), "mode_policy": deepcopy(MODE_POLICY),
        "optimizer": deepcopy(OPTIMIZER_POLICY), "optimizer_steps": training_report["optimizer_steps"], **FLAGS}
    result["representation_id"] = _identity(result)
    _require(result["representation_id"] not in
             (initialization["representation_id"], aligned_checkpoint["representation_id"]),
             "trained aligned generation must have its own identity")
    _require(len(_raw(result)) <= MAX_BYTES, "aligned interface checkpoint exceeds 16 MiB")
    return result


def inspect_interface_checkpoint(checkpoint, *, initialization, plan, batch, replay,
                                 aligned_checkpoint, expected_alignment_file_pins, expected_donor_pins):
    """Inspect the complete native, original and aligned closure before Torch."""
    _helper("gte_decoder_native_batch").inspect_decoder_native_batch(plan, initialization, batch, replay,
        expected_donor_pins=expected_donor_pins)
    _closed(checkpoint, _FIELDS, "aligned trained interface checkpoint")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "aligned interface checkpoint exceeds 16 MiB")
    recomputed = create_interface_checkpoint(initialization, plan, aligned_checkpoint=aligned_checkpoint,
        expected_alignment_file_pins=expected_alignment_file_pins, expected_donor_pins=expected_donor_pins,
        interfaces=checkpoint["interfaces"], training_report=checkpoint["training_report"])
    _same(checkpoint, recomputed, "aligned trained checkpoint does not match its exact start, parents and report")
    return {"schema": "gte-aligned-interface-checkpoint-inspection/v1", "status": "consistent_trained_unqualified",
        "representation_id": checkpoint["representation_id"], "checkpoint_content_sha256": digest(checkpoint),
        "initialization_representation_id": initialization["representation_id"],
        "aligned_representation_id": aligned_checkpoint["representation_id"],
        "aligned_checkpoint_content_sha256": digest(aligned_checkpoint),
        "aligned_start_model_state_sha256": aligned_checkpoint["model_state_sha256"],
        "alignment_file_pins": deepcopy(expected_alignment_file_pins), "primary_start": PRIMARY_START,
        "interface_state_sha256": checkpoint["interface_state_sha256"],
        "model_state_sha256": checkpoint["model_state_sha256"], "optimizer_steps": checkpoint["optimizer_steps"],
        "trainable_tensor_count": 4, "frozen_inherited_tensor_count": 26,
        "training_execution_authenticated": False, "optimizer_resume_supported": False,
        "producer_execution_authenticated": False, "teacher_qualified": False, "production_kd_eligible": False,
        "distillation_executed": False, "encoder_inference_executed": False, "proof_authority": False}


def load_interface_checkpoint(checkpoint, *, initialization, plan, batch, replay,
                              aligned_checkpoint, expected_alignment_file_pins, expected_donor_pins):
    """Load private CPU tensors over the authenticated aligned generation."""
    inspect_interface_checkpoint(checkpoint, initialization=initialization, plan=plan, batch=batch, replay=replay,
        aligned_checkpoint=aligned_checkpoint, expected_alignment_file_pins=expected_alignment_file_pins,
        expected_donor_pins=expected_donor_pins)
    import torch
    with _BASE._cpu_context(torch):
        model = _helper("gte_aligned_decoder").load_aligned_decoder(aligned_checkpoint,
            expected_file_pins=expected_alignment_file_pins, expected_donor_pins=expected_donor_pins)
        parameters = dict(model.named_parameters())
        for name, values in checkpoint["interfaces"].items():
            parameters[name].copy_(torch.tensor(values, dtype=torch.float32, device="cpu"))
        current = {name: value.detach().tolist() for name, value in model.state_dict().items()}
        _require(digest(current) == checkpoint["model_state_sha256"], "reloaded aligned trained state differs")
        _require(all(parameter.device.type == "cpu" and parameter.dtype == torch.float32
                     and parameter.requires_grad is (name in INTERFACES) and parameter.grad is None
                     for name, parameter in model.named_parameters()), "private aligned trained mode policy differs")
        _require(len({parameter.untyped_storage().data_ptr() for parameter in model.parameters()}) == 30,
                 "private aligned trained tensors must have independent storage")
        model.eval()
        model.representation_id = checkpoint["representation_id"]
        model.initialization_representation_id = initialization["representation_id"]
        model.aligned_start_representation_id = aligned_checkpoint["representation_id"]
        return model


__all__ = ["SCHEMA", "REPORT_SCHEMA", "PRIMARY_START", "INTERFACES", "FLAGS", "digest",
           "create_interface_checkpoint", "inspect_interface_checkpoint", "load_interface_checkpoint"]
