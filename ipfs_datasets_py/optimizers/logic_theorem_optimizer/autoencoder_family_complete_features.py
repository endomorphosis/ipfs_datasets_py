"""Complete, compositional training vocabularies for native formula features.

No native IR payload is rewritten. Ordered identifier pieces are numerical
features only; the source-bound native formula remains authoritative. This
version never silently truncates a training vocabulary to fit a feature budget.
It is deliberately incompatible with older feature-checkpoint coordinates.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import re

from . import autoencoder_family_training as codec
from . import autoencoder_family_training_prepared as prepared

SCHEMA = "native-family-complete-compositional-features/v1"
MAX_FEATURES = 262144


def identifier_pieces(token):
    """Preserve case, delimiters and character order while sharing name pieces."""
    if re.fullmatch(r"[a-fA-F0-9]{24,}", token):
        return [token]  # Content hashes are opaque identities, not semantic words.
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+|_|[^\w\s]", token)
    return parts if "".join(parts) == token else [token]


def atom_encoder():
    @lru_cache(maxsize=32768)
    def wire(path, kind, payload):
        return codec._raw([path, kind, *payload]).decode()

    def atoms(value, path=(), depth=0):
        codec._require(depth <= 32, "projection exceeds structural depth bound")
        if isinstance(value, dict):
            yield wire(path, "object", (tuple(sorted(value)),))
            for key, child in sorted(value.items()):
                yield from atoms(child, path + (key,), depth + 1)
        elif isinstance(value, list):
            yield wire(path, "list", (len(value),))
            for index, child in enumerate(value):
                yield from atoms(child, path + (index,), depth + 1)
        elif isinstance(value, str):
            yield wire(path, "string", ())
            for index, token in enumerate(re.findall(r"\w+|[^\w\s]", value)):
                for part_index, part in enumerate(identifier_pieces(token)):
                    yield wire(path, "ordered_identifier_piece", (index, part_index, part))
        else:
            # Do not cache by Python value: True and 1 would alias in an LRU key.
            yield codec._raw([path, "value", value]).decode()
    return atoms, wire.cache_info


def prepare(training_reports, validation_reports, *, max_features=MAX_FEATURES):
    codec._require(type(max_features) is int and 1 <= max_features <= MAX_FEATURES,
                   "bounded feature capacity required")
    atoms, cache = atom_encoder()
    domain, training = prepared._reports(training_reports, atoms=atoms)
    other, validation = prepared._reports(validation_reports, atoms=atoms)
    codec._require(domain == other, "mixed feature domains")
    training_keys = set().union(*(codec._split_keys(row) for row in training_reports))
    tuning_keys = set().union(*(codec._split_keys(row) for row in validation_reports))
    codec._require(not training_keys & tuning_keys, "training/validation source leakage")
    descriptors, vocabularies = {}, {}
    for row in training:
        for name, (descriptor, tokens) in row.items():
            codec._require(name not in descriptors or descriptors[name] == descriptor,
                           "native projection semantics changed")
            descriptors[name] = descriptor
            vocabularies.setdefault(name, set()).update(tokens)
    columns = [[name, token] for name, tokens in sorted(vocabularies.items()) for token in sorted(tokens)]
    codec._require(0 < len(columns) <= max_features,
                   f"complete training vocabulary needs {len(columns)} features; capacity is {max_features}; no atoms were pruned")
    codec._require(len(columns) * (len(training) + len(validation)) <= 33_554_432,
                   "dense feature matrices exceed the 256 MiB budget")
    space = {"schema": SCHEMA, "domain_id": domain, "projections": descriptors, "columns": columns,
        "training_sources": sorted(row["source_digest"] for row in training_reports),
        "training_split_keys": sorted(training_keys), "training_reports_sha256": codec._digest(training_reports),
        "producer_pins": codec._producer_pins(list(training_reports) + list(validation_reports)),
        "feature_selection": {"method": "all_training_atoms_without_pruning", "feature_count": len(columns),
            "capacity": max_features, "retained_atoms": {name: len(tokens) for name, tokens in vocabularies.items()}},
        "normalization": "log1p_l2_per_native_projection", **codec.FALSE}
    codec._validate_producer_pins(space["producer_pins"])
    codec._bind_producers(space, list(training_reports) + list(validation_reports))
    x, mask, spans, coverage = codec._matrix(space, training)
    y, tuning_mask, _, tuning_coverage = codec._matrix(space, validation)
    codec._require(not coverage["untrained_projection_ids"] and all(
        row["unknown_atoms"] == 0 for row in coverage["projections"]), "training vocabulary unexpectedly omitted atoms")
    return {"space": space, "training": x, "training_mask": mask, "validation": y,
            "validation_mask": tuning_mask, "spans": spans, "training_coverage": coverage,
            "validation_coverage": tuning_coverage, "atom_cache": cache()._asdict()}


def encode_reports(space, reports):
    codec._require(space.get("schema") == SCHEMA, "complete compositional feature space required")
    domain, rows = prepared._reports(reports, atoms=atom_encoder()[0])
    codec._require(domain == space["domain_id"], "inference domain differs")
    codec._bind_producers(space, reports)
    return codec._matrix(space, rows)
