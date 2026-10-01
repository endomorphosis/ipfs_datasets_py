"""Versioned, opt-in development settings for the current 384D formula head.

These profiles only configure existing APIs. They do not change either decoder
implementation, historical checkpoint bytes, source guards, or default training.
Each comparison starts a fresh sparse core and formula checkpoint. In particular,
raw_gain10 changes the core binding; its head must not attach to the baseline.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = "current-modal-formula-training-profile/v1"
PROFILE_IDS = ("baseline_v1", "raw_gain10_v1", "reconstruction_x10_v1")
FALSE = {"admitted": False, "formalized": False, "roundtrip_ok": False,
         "qualified": False, "semantic_correctness_verified": False,
         "proof_authority": False, "promotion_performed": False,
         "lake_executed": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def get_training_profile(profile_id, *, domain="legal_ir", runtime_version="current_v2"):
    """Return an independent descriptor; no checkpoint or runtime is opened.

    Pass core_options to open_runtime and formula_options to a fresh head's
    build_checkpoint/formula_options argument. Reuse core_options when loading
    the head. The fixed budget defines a development comparison, not admission.
    """
    _require(domain == "legal_ir" and runtime_version == "current_v2",
             "these training profiles require legal_ir/current_v2")
    _require(type(profile_id) is str and profile_id in PROFILE_IDS, "unknown versioned formula training profile")
    gain = 10 if profile_id == "raw_gain10_v1" else 1
    reconstruction = 10.0 if profile_id == "reconstruction_x10_v1" else 1.0
    descriptor = {
        "schema": SCHEMA, "profile_id": profile_id, "domain": domain,
        "runtime_version": runtime_version, "lineage_id": "current_legal_v2", "dimension": 384,
        "baseline_profile_id": "baseline_v1",
        "core_options": {"compute_device": "cpu", "initial_embedding_scale": 0.2 if gain == 10 else 0.02,
                         "initial_embedding_rotation_scale": 1.0 if gain == 10 else 0.1},
        "formula_options": {"learning_rate": 0.005, "batch_size": 6, "seed": 1729,
                            "hidden_size": 32, "token_embedding_dim": 16, "projection_width": 8,
                            "formula_weight": 1.0, "reconstruction_weight": reconstruction},
        "training_budget": {"epochs": 1000, "max_optimizer_steps": 1000, "max_seconds": 120},
        "raw_gain_relative_to_baseline": gain,
        "raw_gain_scope": "fresh core without learned sparse adjustments; scalar-times-same-pairwise-skew-transform",
        "core_binding_changes_from_baseline": gain != 1,
        "formula_config_changes_from_baseline": ["reconstruction_weight"] if reconstruction != 1.0 else [],
        "fresh_sparse_core_required": True, "fresh_formula_checkpoint_required": True,
        "existing_defaults_changed": False, "decoder_architecture_changed": False,
        "evaluation_targets_allowed_for_fit_or_selection": False, "temperature": 0,
        "scope": "fixed-budget training/tuning diagnostic; single-seed results do not establish generalization",
        **FALSE,
    }
    return {**descriptor, "profile_sha256": hashlib.sha256(_raw(descriptor)).hexdigest()}


def validate_training_profile(value, *, domain="legal_ir", runtime_version="current_v2"):
    """Reject modified or cross-runtime descriptors; return a fresh exact copy."""
    _require(type(value) is dict and type(value.get("profile_id")) is str,
             "versioned training profile mapping required")
    expected = get_training_profile(value["profile_id"], domain=domain, runtime_version=runtime_version)
    _require(_raw(value) == _raw(expected), "training profile differs from its versioned definition")
    return expected


__all__ = ["SCHEMA", "PROFILE_IDS", "get_training_profile", "validate_training_profile"]
