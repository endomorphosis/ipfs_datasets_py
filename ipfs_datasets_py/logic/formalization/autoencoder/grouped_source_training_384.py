"""Leakage-audited recipe for the shared fixed-schema 384D source decoder.

Group IDs identify indivisible split units, not equivalent targets: a group may
contain paraphrases, polarity pairs, and other related source variants. The
caller supplies this grouping; hashes cannot discover semantic paraphrases.
Grouping metadata is audited here and never reaches the numerical decoder.
The underlying checkpoint format and inference contracts remain unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import time

from . import complete_training as api
from . import source_training_v2 as shared
from . import structured_source_384 as structured

SCHEMA = "grouped-structured-source-training-384/v1"
ROW_FIELDS = frozenset({"id", "group_id", "split", "source_text", "embedding", "target"})
DECODER_FIELDS = ("id", "source_text", "embedding", "target")
EXCLUSION_KEYS = ("id", "group_id", "source_sha256", "normalized_source_sha256", "numeric_embedding_sha256")
_require, _raw, digest = shared._require, shared._raw, shared.digest


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pins():
    directory = Path(__file__).parent
    logic = directory.parent.parent
    semantic_files = {"ui_source_contract_384": directory / "ui_source_contract_384.py",
        "ui_semantic_components": logic / "ui_ux_ir/model/components.py",
        "ui_flogic": logic / "ui_ux_ir/formalize/flogic.py"}
    return {"recipe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "public_api_sha256": hashlib.sha256(Path(api.__file__).read_bytes()).hexdigest(),
        "decoder_implementation": structured._implementation(),
        "ui_semantic_contracts": {name: hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            for name, path in semantic_files.items()},
        "scope": "recipe_public_api_named_ui_semantics_and_decoder_declared_modules"}


def _prepare(domain, rows, split):
    _require(type(rows) is list and 1 <= len(rows) <= (2048 if split == "train" else 4096),
        "bounded nonempty grouped rows required")
    for row in rows:
        _require(type(row) is dict and set(row) == ROW_FIELDS, "closed grouped source row schema required")
        _require(type(row["group_id"]) is str and 0 < len(row["group_id"]) <= 512
            and row["group_id"].strip(), "bounded nonempty group ID required")
        _require(type(row["split"]) is str and row["split"] == split,
            "expected " + split + " split; test/canary rows cannot fit or select")
    # The shared owner checks vector dimensions/finiteness, identity bounds, and
    # all four native target grammars. The public fitting API adds its current
    # native semantic checks (including the stricter UI component vocabulary).
    prepared = shared._rows(domain, [{key: row[key] for key in DECODER_FIELDS} for row in rows], training=True)
    bindings, groups_by_identity, targets_by_input = [], {}, {}
    for supplied, row in zip(rows, prepared):
        # Numeric equality must not be bypassed with integer/float spelling or
        # signed zeros. Preserve original embedding bytes in a separate digest.
        numeric = [float(value) if value != 0 else 0. for value in row["embedding"]]
        binding = {"id": row["id"], "group_id": supplied["group_id"], "split": split,
            "source_sha256": _sha(row["source_text"]),
            "normalized_source_sha256": _sha(" ".join(row["source_text"].casefold().split())),
            "embedding_sha256": digest(row["embedding"]), "numeric_embedding_sha256": digest(numeric),
            "target_sha256": digest(row["target"])}
        for key in ("source_sha256", "normalized_source_sha256", "numeric_embedding_sha256"):
            identity = (key, binding[key])
            previous_group = groups_by_identity.setdefault(identity, binding["group_id"])
            _require(previous_group == binding["group_id"],
                "identical source or embedding assigned to different leakage groups")
        # Different labels within a group are legitimate. Identical exact
        # source/numerical inputs with contradictory labels are not trainable
        # deterministically. Casefolded text alone is not semantic equivalence
        # (case can matter in source code), so it is excluded from this check.
        for key in ("source_sha256", "numeric_embedding_sha256"):
            previous_target = targets_by_input.setdefault((key, binding[key]), binding["target_sha256"])
            _require(previous_target == binding["target_sha256"],
                "identical source or numerical input has conflicting targets")
        bindings.append(binding)
    inventory = {key: sorted({row[key] for row in bindings}) for key in EXCLUSION_KEYS}
    return prepared, bindings, inventory


def _exclude(training_inventory, validation_inventory):
    for key in EXCLUSION_KEYS:
        _require(not set(training_inventory[key]) & set(validation_inventory[key]),
            "training/validation " + key + " overlap")


def train_grouped_source_decoder_384(domain, training_rows, validation_rows, *, parent_projection, config=None):
    """Fit the public structured decoder after strict explicit group exclusion.

    Only ``train`` and ``validation`` split labels are accepted. Validation may
    select regularization; no test/canary inputs are accepted. The report binds
    row, group, source, embedding, target, parent, checkpoint, and implementation
    identities without putting corpus metadata into decoder inputs. Throughput
    counts variants and unique groups separately, excludes embedding production,
    and is not an estimate of semantically independent examples per second.
    """
    started = time.monotonic()
    pins = _pins()
    training, train_bindings, train_inventory = _prepare(domain, training_rows, "train")
    validation, validation_bindings, validation_inventory = _prepare(domain, validation_rows, "validation")
    _exclude(train_inventory, validation_inventory)
    fit_started = time.monotonic()
    fitted = api.train_structured_source_decoder_384(domain, training, validation,
        parent_projection=parent_projection, config=config)
    fit_seconds = time.monotonic() - fit_started
    _require(pins == _pins(), "grouped training implementation changed during fitting")
    checkpoint, metrics = fitted["checkpoint"], deepcopy(fitted["metrics"])
    # This sidecar is deliberately separate: editing the format would invalidate
    # existing source-pinned checkpoint loaders and their authority checks.
    recipe = {"schema": SCHEMA, "domain_id": domain, "producer": pins,
        "checkpoint_schema": checkpoint["schema"], "checkpoint_sha256": digest(checkpoint),
        "parent_sha256": checkpoint["parent_sha256"], "config_sha256": digest(checkpoint["config"]),
        "training_bindings": train_bindings, "validation_bindings": validation_bindings,
        "training_inventory": train_inventory, "validation_inventory": validation_inventory,
        "bindings_sha256": digest({"train": train_bindings, "validation": validation_bindings}),
        "grouping_policy": "caller_declared_indivisible_leakage_groups_not_target_equivalence",
        "automatic_semantic_grouping_performed": False,
        "normalization_policy": "casefold_and_whitespace_for_conservative_leakage_exclusion",
        "group_or_split_metadata_used_as_features": False, "test_used_for_selection": False,
        **shared.FALSE}
    total_seconds = time.monotonic() - started
    group_count = len(train_inventory["group_id"])
    report = {"schema": SCHEMA, "recipe": recipe, "recipe_sha256": digest(recipe),
        "training_variant_count": len(training), "training_unique_group_count": group_count,
        "validation_variant_count": len(validation),
        "validation_unique_group_count": len(validation_inventory["group_id"]),
        "public_fit_seconds": fit_seconds, "recipe_pre_report_seconds": total_seconds,
        "training_variants_per_public_fit_second": len(training) / max(fit_seconds, 1e-9),
        "training_groups_per_public_fit_second": group_count / max(fit_seconds, 1e-9),
        "throughput_scope": "complete_public_fit_including_native_preflight_parent_validation_tuning_and_checkpoint",
        "includes_embedding_generation": False, "independent_semantic_examples_estimated": False,
        "checkpoint_format_modified": False, **shared.FALSE}
    return {"checkpoint": checkpoint, "metrics": metrics, "report": report}


__all__ = ["train_grouped_source_decoder_384"]
