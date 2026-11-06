"""Prospective TRAIN optimizer metadata for the unchanged F18 donor profile.

This contract does not build an optimizer, checkpoint, model or admission.
An original owner must independently authenticate inputs, qualify a distinct
numerical profile, establish fresh initial parity and admit any later work.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from . import legal_span_conditions_fullspan_training_v1 as base

SCHEMA = "conditions-fullspan-f18-optimizer-recipe/v1"
MAX_RECIPE_BYTES = 128 * 1024
_BASE_PATH = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_training_v1.py"
_BASE_SHA256 = "56bd0a248a07de09519f95e5c4bae02ab9d8eb1134b483c257c1f7e7bcb07147"
_RECIPE_PATH = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_optimizer_recipe_v1.py"
_FIELDS = frozenset({"schema", "partition", "donor_config", "donor_config_sha256",
    "base_policy", "base_policy_sha256", "optimizer_recipe", "input_bindings",
    "implementation", "authority"})
_CONFIG_FIELDS = frozenset({"hidden_size", "embedding_dim", "projection_width",
    "latent_dimension", "latent_enabled", "residual_scale", "seed", "batch_size",
    "learning_rate"})
_CONFIG_INTS = frozenset({"hidden_size", "embedding_dim", "projection_width",
    "latent_dimension", "seed", "batch_size"})
_AUTHORITY = {name: False for name in (
    "donor_authenticated", "input_origins_verified", "initial_parity_verified",
    "admitted", "native_admission", "model_execution_performed",
    "optimizer_constructed", "training_executed", "qualified",
    "model_gain_claimed", "formalized", "promoted", "semantic_review_performed",
    "Lean_admitted")}


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _source_bytes(path, maximum):
    path = Path(path)
    _need(path.is_file() and not path.is_symlink(), "regular recipe source required")
    _need(0 < path.stat().st_size <= maximum, "bounded recipe source required")
    raw = path.read_bytes()
    _need(0 < len(raw) <= maximum, "bounded recipe source required")
    return raw


_SOURCE_AT_IMPORT = hashlib.sha256(_source_bytes(__file__, 64 * 1024)).hexdigest()
recipe_digest = base.checkpoint_digest


def _positive_number(value, label):
    _need(type(value) in (int, float), "finite positive " + label + " required")
    try:
        valid = math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    _need(valid, "finite positive " + label + " required")


def _canonical(value):
    """Bound exact JSON types before using the original canonical owner."""
    count = [0]
    def visit(item, depth):
        count[0] += 1
        _need(depth <= 16 and count[0] <= 16384, "bounded recipe JSON required")
        kind = type(item)
        if kind is dict:
            _need(all(type(key) is str and len(key) <= MAX_RECIPE_BYTES for key in item),
                  "literal recipe JSON keys required")
            for child in item.values():
                visit(child, depth + 1)
        elif kind is list:
            for child in item:
                visit(child, depth + 1)
        elif kind is float:
            _need(math.isfinite(item), "finite recipe JSON required")
        elif kind is str:
            _need(len(item) <= MAX_RECIPE_BYTES, "bounded recipe JSON required")
        else:
            _need(kind in (int, bool, type(None)), "literal recipe JSON types required")
    visit(value, 0)
    raw = base._checkpoint_raw(value)
    _need(0 < len(raw) <= MAX_RECIPE_BYTES, "bounded recipe JSON required")
    return raw


def _donor_config(value):
    _need(type(value) is dict and set(value) == _CONFIG_FIELDS,
          "closed F18 donor_config required")
    _need(all(type(value[key]) is int for key in _CONFIG_INTS)
          and type(value["latent_enabled"]) is bool
          and type(value["learning_rate"]) is float,
          "typed F18 donor_config required")
    _positive_number(value["residual_scale"], "donor residual_scale")
    _need(value["learning_rate"] == 0.001, "immutable v1 donor learning rate required")
    base._donor_shapes(value)
    _canonical(value)
    return base._detached(value)


def _bindings(value):
    _need(type(value) is dict and set(value) == base.BINDING_FIELDS
          and value.get("schema") == base.BINDINGS_SCHEMA,
          "closed original15 input bindings required")
    for key in base.BINDING_FIELDS - {"schema"}:
        item = value[key]
        _need(type(item) is str and len(item) == 64
              and all(char in "0123456789abcdef" for char in item),
              "literal input SHA256 required: " + key)
    _canonical(value)
    return base._detached(value)


def _implementation():
    base_file = Path(base.__file__)
    _need(hashlib.sha256(_source_bytes(base_file, 128 * 1024)).hexdigest() == _BASE_SHA256,
          "immutable profile56 source required")
    own_file = Path(__file__)
    _need(own_file.resolve() == base_file.resolve().with_name(Path(_RECIPE_PATH).name),
          "recipe must use its original optimizer sibling owner")
    own_digest = hashlib.sha256(_source_bytes(own_file, 64 * 1024)).hexdigest()
    _need(own_digest == _SOURCE_AT_IMPORT, "recipe source changed since import")
    original = base._checkpoint_implementation()
    owners = original.get("owners") if type(original) is dict else None
    _need(type(owners) is list and len([row for row in owners
          if type(row) is dict and row.get("path") == _BASE_PATH
          and row.get("sha256") == _BASE_SHA256]) == 1,
          "original profile56 implementation binding required")
    return {"base": base._detached(original),
            "recipe": {"path": _RECIPE_PATH, "sha256": own_digest}}


def build_optimizer_recipe(*, donor_config, expected_bindings, learning_rate, margin_weight):
    """Describe one prospective LR change; no numeric state or grant is made."""
    donor = _donor_config(donor_config)
    bindings = _bindings(expected_bindings)
    _positive_number(learning_rate, "TRAIN learning_rate")
    _need(type(margin_weight) in (int, float) and margin_weight in (0.0, 0.25)
          and math.isfinite(margin_weight), "explicit matched margin_weight required")
    policy = base.checkpoint_policy(margin_weight=margin_weight)
    optimizer = base._detached(policy["optimizer"])
    optimizer["learning_rate"] = learning_rate
    value = {"schema": SCHEMA, "partition": "TRAIN", "donor_config": donor,
        "donor_config_sha256": recipe_digest(donor), "base_policy": policy,
        "base_policy_sha256": recipe_digest(policy), "optimizer_recipe": optimizer,
        "input_bindings": bindings, "implementation": _implementation(),
        "authority": dict(_AUTHORITY)}
    _canonical(value)
    return base._detached(value)


def validate_optimizer_recipe(recipe, *, donor_config, expected_bindings,
                              learning_rate, margin_weight):
    """Compare to independent caller expectations; return detached metadata.

    The recipe supplies none of its own expected inputs. Successful validation
    establishes this closed metadata contract, not physical input authenticity,
    source custody, initial parity, numerical qualification or admission.
    """
    _need(type(recipe) is dict and set(recipe) == _FIELDS, "closed optimizer recipe required")
    raw = _canonical(recipe)
    expected = build_optimizer_recipe(donor_config=donor_config,
        expected_bindings=expected_bindings, learning_rate=learning_rate,
        margin_weight=margin_weight)
    _need(raw == _canonical(expected), "optimizer recipe differs from independent expectations")
    return base._detached(expected)
