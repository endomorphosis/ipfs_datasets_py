"""Import reviewed native pairs without turning retrieval labels into supervision.

Review declarations bind supplied source text and native targets; they are not
authenticated attestations or semantic proofs. Separately bound embedding rows
must use the parent's embedding pipeline. No embedding computation, source
execution, fitting, checkpoint mutation, or publication occurs here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path

from . import contracts as c
from . import numerics, profiles
from .. import complete_training, grouped_source_training_384 as grouped
from .. import structured_source_384 as decoder

PAIRS_SCHEMA = "ir384-reviewed-source-pairs/v1"
EMBEDDINGS_SCHEMA = "ir384-source-embeddings/v1"
REVIEW_SCHEMA = "ir384-source-native-review/v1"
EXPORT_SCHEMA = "ir384-reviewed-pair-export/v1"
_TELEMETRY = {"batch_size", "device", "encode_rows_per_second", "encode_seconds",
              "load_seconds", "max_tokens_observed", "rows"}
_PAIR_KEYS = {"id", "split", "source_text", "target", "source_identity", "review"}
_IDENTITY_KEYS = {"source_uri", "source_revision", "record_id", "leakage_family_ids"}
_REVIEW_KEYS = {"schema", "decision", "scope", "reviewer", "rationale", "source_sha256",
                "target_sha256", "source_identity_sha256"}


def _text(value, maximum, message):
    c.require(type(value) is str and bool(value.strip()) and len(value.encode()) <= maximum, message)


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _embedding_signature(provenance):
    c.require(type(provenance) is dict and len(c.raw(provenance)) <= 16384,
              "bounded explicit embedding provenance required")
    c.require(type(provenance.get("dimension")) is int and provenance["dimension"] == 384,
              "embedding provenance requires dimension 384")
    _text(provenance.get("model_id"), 256, "explicit embedding model identity required")
    c.require(provenance["model_id"] != "caller_supplied" and
              type(provenance.get("revision")) is str and
              c.COMMIT.fullmatch(provenance["revision"]), "immutable embedding model revision required")
    c.require(type(provenance.get("normalized")) is bool and
              provenance.get("dtype") in ("float32", "float64") and
              provenance.get("truncated") is False,
              "normalization, dtype and no-truncation embedding provenance required")
    assets = provenance.get("assets")
    c.require(type(assets) is list and 1 <= len(assets) <= 128, "embedding assets must be pinned")
    seen = set()
    for asset in assets:
        c.require(type(asset) is dict and set(asset) == {"name", "bytes", "sha256"},
                  "closed embedding asset descriptor required")
        _text(asset["name"], 1024, "bounded embedding asset name required")
        c.require(asset["name"] not in seen and type(asset["bytes"]) is int and asset["bytes"] > 0
                  and type(asset["sha256"]) is str and c.SHA.fullmatch(asset["sha256"]),
                  "unique hash-bound embedding assets required")
        seen.add(asset["name"])
    result = {key: deepcopy(value) for key, value in provenance.items() if key not in _TELEMETRY}
    result["assets"] = sorted(result["assets"], key=lambda item: item["name"])
    return result


def _validate_pair(pair):
    c.require(type(pair) is dict and set(pair) == _PAIR_KEYS, "closed reviewed pair required")
    _text(pair["id"], 256, "bounded pair identity required")
    c.require(pair["split"] in ("train", "validation"),
              "explicit train/validation split required; test and canary cannot fit")
    _text(pair["source_text"], 1048576, "bounded nonempty source text required")
    identity = pair["source_identity"]
    c.require(type(identity) is dict and set(identity) == _IDENTITY_KEYS,
              "closed source identity and leakage families required")
    _text(identity["source_uri"], 4096, "bounded source URI required")
    _text(identity["record_id"], 1024, "bounded source record identity required")
    c.require(type(identity["source_revision"]) is str and
              c.COMMIT.fullmatch(identity["source_revision"]), "immutable source revision required")
    families = identity["leakage_family_ids"]
    c.require(type(families) is list and 1 <= len(families) <= 64,
              "one to 64 declared source leakage families required")
    for family in families:
        _text(family, 512, "bounded declared source leakage family required")
    c.require(len(set(families)) == len(families), "duplicate source leakage families")
    review = pair["review"]
    c.require(type(review) is dict and set(review) == _REVIEW_KEYS and
              review["schema"] == REVIEW_SCHEMA and review["decision"] == "accepted" and
              review["scope"] == "source_to_native_ir", "accepted source-to-native review required")
    _text(review["reviewer"], 512, "review declaration must identify its reviewer")
    _text(review["rationale"], 8192, "review declaration must explain its source/native decision")
    c.require(review["source_sha256"] == _sha(pair["source_text"]) and
              review["target_sha256"] == c.digest(pair["target"]) and
              review["source_identity_sha256"] == c.digest(identity),
              "review declaration differs from its exact source, native target or source identity")


def _groups(pairs, embeddings):
    """Join declared families and byte/numeric identities before auditing splits."""
    parents = list(range(len(pairs)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    owners, evidence = {}, []
    for index, pair in enumerate(pairs):
        identity = pair["source_identity"]
        numeric = [float(value) if value != 0 else 0. for value in embeddings[pair["id"]]]
        keys = [("family", key) for key in identity["leakage_family_ids"]]
        keys += [("record", c.digest({key: identity[key] for key in _IDENTITY_KEYS - {"leakage_family_ids"}})),
                 ("stable_record", c.digest({key: identity[key] for key in ("source_uri", "record_id")})),
                 ("source", _sha(pair["source_text"])),
                 ("normalized_source", _sha(" ".join(pair["source_text"].casefold().split()))),
                 ("numeric_embedding", c.digest(numeric))]
        evidence.append(keys)
        for key in keys:
            if key in owners:
                parents[find(index)] = find(owners[key])
            else:
                owners[key] = index
    components = {}
    for index in range(len(pairs)):
        components.setdefault(find(index), []).append(index)
    groups, audit = {}, []
    for indexes in components.values():
        splits = {pairs[index]["split"] for index in indexes}
        c.require(len(splits) == 1, "source-family or source/vector identity crosses train/validation")
        keys = sorted({key for index in indexes for key in evidence[index]})
        group_id = "reviewed-pairs:" + c.digest(keys)
        for index in indexes:
            groups[pairs[index]["id"]] = group_id
        audit.append(dict(group_id=group_id, split=next(iter(splits)),
            row_ids=sorted(pairs[index]["id"] for index in indexes),
            declared_families=sorted(key[1] for key in keys if key[0] == "family")))
    return groups, sorted(audit, key=lambda item: item["group_id"])


def export_reviewed_pairs(domain, pairs_path, embeddings_path, output_dir, *, base_path=None,
                          cache_dir=None, local_files_only=False):
    """Validate a bounded reviewed pair export against a frozen published parent.

    The returned train/validation/source paths feed ``runner.prepare_round``.
    Successful import establishes identity, schema and declared-review checks;
    it does not establish label truth or reproduce embedding model computation.
    """
    c.require(domain in c.DOMAINS and type(local_files_only) is bool, "known domain and boolean cache policy required")
    pairs, pairs_ref = c.read_json_bound(pairs_path)
    embedded, embedding_ref = c.read_json_bound(embeddings_path)
    c.require(type(pairs) is dict and set(pairs) == {"schema", "domain_id", "source_descriptor", "rows"}
              and pairs["schema"] == PAIRS_SCHEMA and pairs["domain_id"] == domain,
              "reviewed native pairs manifest required; raw spans and weak targets cannot substitute")
    descriptor = pairs["source_descriptor"]
    numerics._source_descriptor(descriptor)
    c.require(type(descriptor.get("redistribution_allowed")) is bool,
              "explicit source redistribution decision required")
    records = pairs["rows"]
    c.require(type(records) is list and 2 <= len(records) <= 6144, "bounded reviewed pair list required")
    seen = set()
    for pair in records:
        _validate_pair(pair)
        c.require(pair["id"] not in seen, "duplicate pair identity")
        seen.add(pair["id"])
    c.require(type(embedded) is dict and set(embedded) == {"schema", "provenance", "rows"}
              and embedded["schema"] == EMBEDDINGS_SCHEMA,
              "separate source-bound embeddings manifest required")
    signature = _embedding_signature(embedded["provenance"])
    c.require(type(embedded["rows"]) is list and len(embedded["rows"]) == len(records),
              "one embedding record per reviewed pair required")
    by_id, pair_index = {}, {pair["id"]: pair for pair in records}
    for row in embedded["rows"]:
        c.require(type(row) is dict and set(row) == {"id", "source_sha256", "embedding_sha256", "embedding"}
                  and type(row["id"]) is str and row["id"] in pair_index and row["id"] not in by_id,
                  "unique closed source-bound embedding row required")
        vector = row["embedding"]
        c.require(type(vector) is list and len(vector) == 384 and
                  all(type(value) in (int, float) and math.isfinite(value) for value in vector),
                  "exactly 384 finite numerical embedding coordinates required")
        c.require(row["source_sha256"] == pair_index[row["id"]]["review"]["source_sha256"] and
                  row["embedding_sha256"] == c.digest(vector), "embedding source or vector digest differs")
        if signature["normalized"]:
            c.require(abs(math.sqrt(math.fsum(value * value for value in vector)) - 1.) <= 1e-4,
                      "embedding vector violates declared L2 normalization")
        by_id[row["id"]] = vector
    if base_path is None:
        base_path = profiles.load_parent(domain, cache_dir=cache_dir, local_files_only=local_files_only)
    base, base_ref = c.read_json_bound(base_path)
    numerics._base(base)
    c.require(base["domain_id"] == domain, "parent checkpoint belongs to another domain")
    c.require(signature == _embedding_signature(base["config"]["embedding_provenance"]),
              "embedding pipeline differs from frozen parent provenance")
    groups, grouping_audit = _groups(records, by_id)
    rows = [dict(id=pair["id"], group_id=groups[pair["id"]], split=pair["split"],
                 source_text=pair["source_text"], embedding=by_id[pair["id"]], target=pair["target"])
            for pair in sorted(records, key=lambda row: row["id"])]
    training = [row for row in rows if row["split"] == "train"]
    validation = [row for row in rows if row["split"] == "validation"]
    train_rows, train_binding, train_inventory = grouped._prepare(domain, training, "train")
    validation_rows, validation_binding, validation_inventory = grouped._prepare(domain, validation, "validation")
    grouped._exclude(train_inventory, validation_inventory)
    complete_training._preflight_source_targets(domain, train_rows, validation_rows)
    import numpy as np
    decoder._targets(np, train_rows, base["target_schema"])
    decoder._targets(np, validation_rows, base["target_schema"])
    audit = dict(schema=EXPORT_SCHEMA, domain_id=domain,
        parent_checkpoint=base_ref, parent_target_schema_sha256=c.digest(base["target_schema"]),
        inputs=dict(pairs=pairs_ref, embeddings=embedding_ref),
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        embedding_pipeline=signature, embedding_pipeline_sha256=c.digest(signature),
        review_declarations=[dict(id=pair["id"], source_identity=pair["source_identity"], review=pair["review"])
                             for pair in sorted(records, key=lambda row: row["id"])],
        groups=grouping_audit, training_bindings=train_binding, validation_bindings=validation_binding,
        training_rows=len(training), validation_rows=len(validation),
        training_rows_sha256=c.digest(training), validation_rows_sha256=c.digest(validation),
        supervision="caller_reviewed_native_pairs_with_exact_content_bindings",
        review_authenticity_verified=False, review_semantics_independently_verified=False,
        embedding_computation_replayed=False, undeclared_semantic_paraphrases_discovered=False,
        grouping_policy="transitive_declared_source_families_and_source_or_vector_identities",
        frozen_vocabulary_verified=True, training_performed=False, source_executed=False,
        **c.FALSE)
    audit["audit_sha256"] = c.digest(audit)
    source = deepcopy(descriptor)
    c.require("reviewed_pair_export" not in source, "source descriptor already carries an export binding")
    source["reviewed_pair_export"] = dict(schema=EXPORT_SCHEMA, audit_sha256=audit["audit_sha256"],
        input_pair_sha256=pairs_ref["sha256"], input_embeddings_sha256=embedding_ref["sha256"],
        parent_checkpoint_sha256=base_ref["sha256"], embedding_pipeline_sha256=c.digest(signature),
        supervision=audit["supervision"], review_semantics_independently_verified=False)
    numerics._source_descriptor(source)
    root = Path(output_dir).absolute()
    paths = {}
    for name, value in (("training", training), ("validation", validation), ("source", source), ("audit", audit)):
        paths[name + "_path"] = str(c.write_json(root / (name + ".json"), value))
    return dict(schema=EXPORT_SCHEMA, domain_id=domain, **paths, base_path=str(Path(base_path).absolute()),
        training_rows=len(training), validation_rows=len(validation), groups=len(grouping_audit),
        audit_sha256=audit["audit_sha256"], **c.FALSE)


__all__ = ["export_reviewed_pairs"]
