"""Pinned security training declarations and native dependency planning.

The profile selects a corpus, a separately owned LegalIR initializer and code
logic projections. It neither starts training nor turns a classification label
or a compiled declaration into a proved program property.
"""
from __future__ import annotations

import json

SCHEMA = "security-code-training-profile@1"


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _legal_parent(value):
    from .published_legal_initializer import validate_published_legal_source_pin
    validate_published_legal_source_pin(value)
    return json.loads(_json(value))


def build_security_code_training_profile(*, corpus_profile: dict, legal_parent: dict) -> dict:
    """Build a declaration; source acquisition/verification remains an explicit task."""
    from ipfs_datasets_py.logic.security_ir.cvefixes.hf_source import HuggingFaceSourcePin
    from ipfs_datasets_py.logic.security_ir.code_logic_projection import describe_code_logic_projection_profile
    from .security_cve_corpus import build_security_corpus_profile
    from ipfs_datasets_py.logic.security_ir.code_program_derivation import describe_code_program_derivation_profile
    from .security_cve_training_source import BenchmarkExclusions
    from ipfs_datasets_py.logic.ir_core.identity import canonical_identity

    if type(corpus_profile) is not dict:
        raise ValueError("closed corpus profile required")
    rebuilt = build_security_corpus_profile(pin=HuggingFaceSourcePin.from_dict(corpus_profile["pin"]),
        repository_splits=corpus_profile["repository_splits"], graph_shards=corpus_profile["graph_shards"],
        exclusions=BenchmarkExclusions(**corpus_profile["benchmark_exclusions"]), **corpus_profile["budget"])
    if _json(rebuilt) != _json(corpus_profile):
        raise ValueError("corpus profile contains altered semantics or authority")
    profile = {"schema": SCHEMA, "corpus": rebuilt, "legal_parent": _legal_parent(legal_parent),
        "code_logic": describe_code_logic_projection_profile(),
        "source_modeling": describe_code_program_derivation_profile(),
        "initialization": {"shared_component": "compatible feature_embedding_weights[token:*] rows",
            "preserve_values_and_dimensions": True, "random_backbone_initialization": False,
            "legal_heads_reused_as_code_heads": False, "legal_checkpoint_writes": False,
            "new_heads": "separate security namespace; explicit architecture and training receipt required"},
        "training": {"split_before_fit": True, "fit_splits": ["train"],
            "model_selection_splits": ["validation"], "held_out_splits": ["test"],
            "input_features": "source-body lexical and supported AST observations only",
            "classification_targets": "native audit/CWE/polarity candidates",
            "code_logic_targets": "source-bound typed modeling declarations with exact native projections",
            "declarations_are_verified_source_semantics": False,
            "proved_targets_require_independent_evidence": True,
            "missing_typed_evidence": "explicit frontier; never infer formulas from CWE labels",
            "formula_head_trained": False, "heldout_evaluated": False, "training_started": False},
        "authority": "candidate_training_declaration", "proof_authority": False,
        "execution_authority": False, "publication_authority": False}
    return {**profile, "profile_cid": canonical_identity(profile, domain="autoencoder/security-training", schema_version=SCHEMA).cid}


def validate_security_code_training_profile(profile: dict) -> dict:
    if type(profile) is not dict or profile.get("schema") != SCHEMA:
        raise ValueError("security code training profile required")
    rebuilt = build_security_code_training_profile(corpus_profile=profile["corpus"], legal_parent=profile["legal_parent"])
    if _json(rebuilt) != _json(profile):
        raise ValueError("training source, family projection, split, or authority changed")
    return rebuilt
