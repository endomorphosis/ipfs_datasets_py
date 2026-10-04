"""Validate comparison evidence without opening sealed target JSON for parsing."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_digest(value):
    """Match the frozen preparer's exact canonical JSON encoding."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _bytes(path):
    path = Path(path)
    require(path.stat().st_size <= 64 * 1024 ** 2, "input artifact exceeds 64MiB")
    return path.read_bytes()


def _verified(ref):
    raw = _bytes(ref["path"])
    require(len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
            "artifact bytes/hash differ from recorded reference")
    return raw


def _parse(raw):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("nonfinite JSON value: " + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def validate_inputs(corpus, challenge_targets_path):
    """Bind all visible rows/vectors to frozen plan and verified native receipts.

    The sealed file is hashed as bytes only. No JSON parsing or target decoding
    occurs until the caller finishes training and explicitly opens that file.
    """
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as formula
    require(corpus["schema"] == "legal-decoder-comparison-corpus/v1", "comparison corpus schema differs")
    require(corpus["label_origin"] == "authored_synthetic_not_legal_authority", "authored provenance required")
    require(corpus["independently_reviewed"] is False, "corpus misstates independent review")
    plan = _parse(_verified(corpus["frozen_plan"]))
    require(plan["schema"] == "legal-decoder-comparison-frozen-plan/v1", "frozen plan schema differs")
    sealed_bytes = _bytes(challenge_targets_path)
    sealed_ref = corpus["sealed_targets"]
    require(len(sealed_bytes) == sealed_ref["bytes"] and hashlib.sha256(sealed_bytes).hexdigest() == sealed_ref["sha256"],
            "sealed target file differs from frozen reference")
    splits = corpus["splits"]
    require({key: len(rows) for key, rows in splits.items()} == plan["split_counts"], "frozen split counts differ")
    plan_rows = {row["id"]: row for row in plan["rows"]}
    require(len(plan_rows) == len(plan["rows"]), "duplicate identities in frozen plan")
    all_rows = {}
    source_seen, target_seen, groups = {}, {}, {}
    for split, rows in splits.items():
        for row in rows:
            identifier = row["id"]
            require(identifier not in all_rows and identifier in plan_rows, "duplicate or unplanned source identity")
            all_rows[identifier] = row
            planned = plan_rows[identifier]
            source_sha = hashlib.sha256(row["source_text"].encode()).hexdigest()
            require(planned["split"] == split and source_sha == row["source_sha256"] == planned["source_sha256"],
                    "source content or split differs from frozen plan")
            if split in ("challenge", "oov"):
                require("canonical_ir" not in row, "sealed or OOV input contains reference target")
                require(row.get("canonical_target_sha256") == planned["canonical_target_sha256"],
                        "sealed target digest differs from frozen plan")
            else:
                formula._rule(row["canonical_ir"])
                require(canonical_digest(row["canonical_ir"]) == row["canonical_target_sha256"] == planned["canonical_target_sha256"],
                        "visible canonical target differs from frozen plan")
            if split != "oov":
                normalized = " ".join(re.findall(r"\w+|[^\w\s]", row["source_text"].casefold(), flags=re.UNICODE))
                target_sha = row["canonical_target_sha256"]
                require(normalized not in source_seen and target_sha not in target_seen,
                        "normalized source or complete target overlaps partitions")
                source_seen[normalized] = split
                target_seen[target_sha] = split
            if split in ("development", "challenge"):
                for key in ("family_group", "actor_action_group"):
                    group = (key, row[key])
                    require(group not in groups or groups[group] == split, "new family group crosses split")
                    groups[group] = split
    require(set(all_rows) == set(plan_rows), "corpus does not cover all frozen identities")
    frozen_codec = formula.fit_codec([{key: row[key] for key in ("id", "source_text", "canonical_ir")}
                                     for row in splits["train"]])
    require(canonical_digest(frozen_codec) == plan["leakage_checks"]["frozen_codec_sha256"],
            "training-only vocabulary differs from frozen plan")
    for split in ("train", "development", "tuning", "challenge"):
        for row in splits[split]:
            formula.encode_source(frozen_codec, row["source_text"])
            if "canonical_ir" in row:
                formula.encode_target(frozen_codec, row["canonical_ir"])
    def resolver(ref):
        path = Path(corpus["source_paths"][ref["sha256"]])
        raw = _bytes(path)
        require(len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
                "embedding source artifact differs")
        return path
    receipts = {}
    for ref in corpus["embedding_receipts"]:
        require(ref["sha256"] not in receipts, "duplicate embedding receipt")
        loaded = codec.load_embedding_production_receipt(ref["path"], expected_sha256=ref["sha256"],
            expected_size_bytes=ref["bytes"], resolver=resolver)
        data = loaded.to_dict()
        require(data["execution"]["kind"] == "native", "embedding receipt is not native production")
        require(data["model"] == corpus["model"] and data["model_assets"] == corpus["model_assets"],
                "embedding model provenance differs across receipts")
        receipts[ref["sha256"]] = ({row["input_id"]: row for row in data["inputs"]},
                                  {row["input_id"]: row for row in data["results"]})
    bindings = _parse(_verified(corpus["source_bindings"]))
    require(len(bindings) == len(all_rows), "embedding binding coverage differs")
    seen, statuses = set(), Counter()
    for binding in bindings:
        identifier = binding["id"]
        require(identifier not in seen and identifier in all_rows, "embedding binding identities differ")
        seen.add(identifier)
        row, planned = all_rows[identifier], plan_rows[identifier]
        inputs, results = receipts[binding["receipt_sha256"]]
        source, result = inputs[binding["input_id"]], results[binding["input_id"]]
        require(binding["split"] == planned["split"] and binding["source_sha256"] == row["source_sha256"]
                == source["source"]["artifact"]["sha256"] and source["text"] == row["source_text"],
                "embedding input source binding differs")
        status = result["status"]
        require(row.get("embedding_status", status) == status, "embedding disposition differs")
        statuses[status] += 1
        if status != "embedded":
            require(planned["split"] == "oov" and row["embedding"] is None, "missing native vector outside OOV")
            continue
        vector = row["embedding"]
        require(type(vector) is list and len(vector) == 384 and all(type(v) in (int, float)
                and math.isfinite(v) for v in vector), "embedding must contain 384 finite numbers")
        try:
            bits = struct.pack(">384f", *vector)
        except (OverflowError, struct.error) as error:
            raise ValueError("embedding cannot be represented as float32") from error
        require(bits == bytes.fromhex(result["vector"]["bits"]), "embedding float32 bits differ from receipt")
        require(vector == list(struct.unpack(">384f", bits)), "embedding contains unrecorded float64 precision")
    return {"schema": "legal-decoder-comparison-input-validation/v1", "rows_verified": len(all_rows),
            "native_receipts_verified": len(receipts), "embedding_statuses": dict(statuses),
            "frozen_plan_sha256": corpus["frozen_plan"]["sha256"],
            "sealed_targets_sha256": sealed_ref["sha256"], "sealed_targets_parsed": False,
            "source_vector_binding_verified": True, "canonical_target_hashes_verified": "visible targets only",
            "training_only_vocabulary_verified": True, "semantic_qualification": False}
