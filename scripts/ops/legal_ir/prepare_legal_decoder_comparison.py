#!/usr/bin/env python3
"""Freeze a compositional decoder comparison and source-only native embeddings.

The generated targets specify an authored toy grammar, not reviewed legal
semantics. Sealed targets are written separately before any model is evaluated.
The existing 99 vectors are reused only after source and receipt verification.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
FIXTURE = ROOT / "tests/fixtures/legal_formula_learning/v1.json"
ARTIFACTS = ROOT.parents[1] / "artifacts"
PRIOR = ARTIFACTS / "legal-decoder-pilot-20261002/prepared/corpus.json"
QUEUE = ARTIFACTS / "legal-decoder-pilot-20261002/review-queue.json"
ORIGINAL_SPLITS = ("train", "tuning", "heldout", "regression")
LABEL = "authored_synthetic_not_legal_authority"
DATASET_REVISION = "765176c6db79ba65c1697c21dead43666350b730"
DEV_GROUPS = {("agency", "disclose"), ("Company A", "retain"), ("officer", "submit")}


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def normalized_source(text):
    return " ".join(re.findall(r"\w+|[^\w\s]", text.casefold(), flags=re.UNICODE))


def save(path, value):
    raw = canonical_bytes(value)
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return {"path": str(Path(path).resolve()), "sha256": sha(raw), "bytes": len(raw)}


def file_ref(path):
    raw = Path(path).read_bytes()
    return {"path": str(Path(path).resolve()), "sha256": sha(raw), "bytes": len(raw)}


def verify_ref(ref):
    raw = Path(ref["path"]).read_bytes()
    if len(raw) != ref["bytes"] or sha(raw) != ref["sha256"]:
        raise ValueError("artifact content differs from recorded reference")
    return raw


def make_panels(fixture):
    """Generate all predeclared object swaps, grouping modality minimal pairs."""
    if fixture.get("provenance") != LABEL:
        raise ValueError("authored fixture provenance required")
    panels = {name: [] for name in ("development", "challenge")}
    actors = (("agency", "The agency"), ("Company A", "Company A"), ("officer", "The officer"))
    normal_objects = {"disclose": "records", "retain": "the file", "submit": "backup report"}
    modalities = (("O", "shall"), ("P", "may"), ("F", "shall not"))
    qualifiers = (
        ("plain", "", [], []),
        ("exception", " unless emergency", ["emergency"], []),
        ("deadline", " within 10 days", [], ["within 10 days"]),
        ("minimum", " for at least 20 days", [], ["at least 20 days"]),
        ("deadline-exception", " within 10 days unless emergency", ["emergency"], ["within 10 days"]),
        ("minimum-exception", " for at least 20 days unless emergency", ["emergency"], ["at least 20 days"]),
    )
    for actor, subject in actors:
        for action, usual_object in normal_objects.items():
            split = "development" if (actor, action) in DEV_GROUPS else "challenge"
            group = actor.casefold().replace(" ", "_") + "-" + action
            for obj in normal_objects.values():
                if obj == usual_object:
                    continue
                for qualifier, suffix, exceptions, temporal in qualifiers:
                    family = "object-swap-" + group + "-" + obj.replace(" ", "_") + "-" + qualifier
                    for modality, verb in modalities:
                        panels[split].append({
                            "id": family + "-" + modality.lower(),
                            "source_text": f"{subject} {verb} {action} {obj}{suffix}.",
                            "canonical_ir": {"rules": [{"modality": modality, "actor": actor,
                                "action": action, "object": obj, "conditions": [],
                                "exceptions": list(exceptions), "temporal": list(temporal)}]},
                            "family_group": family, "actor_action_group": group,
                            "qualifier_pattern": qualifier, "provenance": LABEL,
                        })
    check_panels(fixture, panels)
    return panels


def check_panels(fixture, panels):
    """Reject content leakage, group leakage and accidental evaluation vocabulary."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as codec
    frozen_codec = codec.fit_codec(fixture["train"])
    sources, targets, ids = {}, {}, set()
    for split in ORIGINAL_SPLITS:
        for row in fixture[split]:
            for digest, table, kind in ((sha(normalized_source(row["source_text"]).encode()), sources, "source"),
                                       (sha(canonical_bytes(row["canonical_ir"])), targets, "target")):
                if digest in table:
                    raise ValueError(kind + " overlaps existing fixture")
                table[digest] = split
            ids.add(row["id"])
    families, groups = {}, {}
    for split, rows in panels.items():
        for row in rows:
            if row["id"] in ids:
                raise ValueError("duplicate row id")
            ids.add(row["id"])
            for digest, table, kind in ((sha(normalized_source(row["source_text"]).encode()), sources, "source"),
                                       (sha(canonical_bytes(row["canonical_ir"])), targets, "target")):
                if digest in table:
                    raise ValueError(kind + " overlaps another partition")
                table[digest] = split
            for key, table in ((row["family_group"], families), (row["actor_action_group"], groups)):
                if key in table and table[key] != split:
                    raise ValueError("minimal-pair family or actor/action group crosses partitions")
                table[key] = split
            codec.encode_source(frozen_codec, row["source_text"])
            codec.encode_target(frozen_codec, row["canonical_ir"])
    return {"source_and_complete_target_overlap": 0, "new_family_group_overlap": 0,
            "new_actor_action_group_overlap": 0,
            "vocabulary_fit_split": "original train72 only", "new_unknown_source_tokens": 0,
            "new_unknown_target_atoms": 0, "frozen_codec_sha256": sha(canonical_bytes(frozen_codec))}


def oov_panel(queue, frozen_codec):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as codec
    if queue.get("repository") != "justicedao/uscode-autoformal-span-cache" or queue.get("revision") != DATASET_REVISION:
        raise ValueError("OOV queue must identify pinned dataset revision")
    rows = []
    for item in queue["entries"]:
        variants = item["source_text_variants"]
        if len(variants) != 1 or not item["source_text_consistent_across_occurrences"]:
            raise ValueError("OOV span must have one exact source text")
        text = variants[0]
        try:
            codec.encode_source(frozen_codec, text)
            reason = None
        except codec.CodecError as error:
            reason = str(error)
        rows.append({"id": item["source_span_id"], "source_text": text,
                     "source_sha256": sha(text.encode()), "legal_ids": item["legal_ids"],
                     "source_codec_rejection": reason, "provenance": "unreviewed_dataset_observation",
                     "target_available": False, "training_qualified": False})
    return rows


def prepare(output_directory, *, fixture=FIXTURE, prior_corpus=PRIOR, review_queue=QUEUE):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as receipt_codec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan
    require_workspace_logic_tree()
    started = time.monotonic()
    fixture_ref, prior_ref, queue_ref = map(file_ref, (fixture, prior_corpus, review_queue))
    authored = json.loads(verify_ref(fixture_ref))
    previous = json.loads(verify_ref(prior_ref))
    queue = json.loads(verify_ref(queue_ref))
    if previous["fixture"]["sha256"] != fixture_ref["sha256"]:
        raise ValueError("previous embedding fixture hash does not match")
    panels = make_panels(authored)
    leakage = check_panels(authored, panels)
    frozen_codec = legal_formula_codec.fit_codec(authored["train"])
    panels["oov"] = oov_panel(queue, frozen_codec)
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    plan_rows = [{"id": row["id"], "split": split,
                  "source_sha256": sha(row["source_text"].encode()),
                  "canonical_target_sha256": sha(canonical_bytes(row["canonical_ir"])) if "canonical_ir" in row else None}
                 for split, rows in {**{s: authored[s] for s in ORIGINAL_SPLITS}, **panels}.items() for row in rows]
    plan = {"schema": "legal-decoder-comparison-frozen-plan/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "fixture": fixture_ref, "prior_corpus": prior_ref, "review_queue": queue_ref,
            "preparer": file_ref(__file__), "leakage_checks": leakage, "rows": plan_rows,
            "split_counts": dict(Counter(row["split"] for row in plan_rows)),
            "target_origin": LABEL, "independently_reviewed": False,
            "policy": {
                "model_consulted_for_selection": False, "fixed_before_model_evaluation": True,
                "fit": ["train", "development"], "optimizer_selection": ["tuning"],
                "sealed_final_evaluation": ["challenge"],
                "previously_exposed_diagnostic_panels": ["heldout", "regression"],
                "challenge": "all known object swaps over remaining six actor/action groups; six qualifier patterns; O/P/F minimal-pair triples together",
                "development_groups": sorted([list(group) for group in DEV_GROUPS]),
                "vocabulary": "Fit only on original train72; development and challenge require no new tokens or atoms",
                "sealed_meaning": "Targets are stored in a separate file; procedural isolation, not a security boundary",
                "oov": "Exact observed dataset sources without inferred targets; no semantic accuracy metric",
            }}
    plan_ref = save(output / "frozen-plan.json", plan)
    save(output / "frozen-training-codec.json", frozen_codec)
    sealed_rows = [{"id": row["id"], "canonical_ir": row["canonical_ir"],
                    "source_sha256": sha(row["source_text"].encode()),
                    "canonical_target_sha256": sha(canonical_bytes(row["canonical_ir"]))}
                   for row in panels["challenge"]]
    sealed_ref = save(output / "sealed-evaluation-targets.json", {
        "schema": "legal-decoder-comparison-sealed-targets/v1", "split": "challenge",
        "frozen_plan": plan_ref, "label_origin": LABEL, "targets": sealed_rows})

    sources_dir = output / "sources"
    sources_dir.mkdir()
    source_paths = {}
    def source_path(text):
        raw = text.encode()
        digest = sha(raw)
        if digest not in source_paths:
            path = sources_dir / (digest + ".txt")
            with path.open("xb") as stream:
                stream.write(raw)
            source_paths[digest] = str(path)
        return digest
    def resolver(ref):
        path = Path(source_paths[ref["sha256"]])
        if path.stat().st_size != ref["bytes"] or sha(path.read_bytes()) != ref["sha256"]:
            raise ValueError("source bytes changed")
        return path
    for split in ORIGINAL_SPLITS:
        for row in authored[split]:
            source_path(row["source_text"])
    old_receipt_ref = previous["embedding_receipt"]
    old_receipt = receipt_codec.load_embedding_production_receipt(old_receipt_ref["path"],
        expected_sha256=old_receipt_ref["sha256"], expected_size_bytes=old_receipt_ref["bytes"], resolver=resolver)
    old_data = old_receipt.to_dict()
    if old_data["model"] != previous["model"] or old_data["model_assets"] != previous["model_assets"]:
        raise ValueError("reused receipt model provenance differs")
    if old_data["producer"]["code_sha256"] != sha(Path(producer.__file__).read_bytes()):
        raise ValueError("reused receipt embedding producer differs from current producer")
    copied_ref = old_receipt.save(output / "reused-embedding-production.json", resolver=resolver)
    old_vectors = {row["input_id"]: list(struct.unpack(">384f", bytes.fromhex(row["vector"]["bits"])))
                   for row in old_data["results"] if row["status"] == "embedded"}
    old_bindings = json.loads(verify_ref(previous["source_bindings"]))
    old_bindings = {row["id"]: row for row in old_bindings}
    splits, bindings = {}, []
    for split in ORIGINAL_SPLITS:
        splits[split] = []
        prior_rows = {row["id"]: row for row in previous["splits"][split]}
        for row in authored[split]:
            binding = old_bindings[row["id"]]
            vector = old_vectors[binding["input_id"]]
            if (prior_rows[row["id"]]["source_text"] != row["source_text"] or
                    prior_rows[row["id"]]["canonical_ir"] != row["canonical_ir"] or
                    prior_rows[row["id"]]["embedding"] != vector or
                    binding["source_sha256"] != sha(row["source_text"].encode())):
                raise ValueError("previous vector or source/target content differs")
            digest = source_path(row["source_text"])
            splits[split].append({**row, "embedding": vector, "source_sha256": digest,
                "canonical_target_sha256": sha(canonical_bytes(row["canonical_ir"])), "provenance": LABEL})
            bindings.append({"id": row["id"], "split": split, "input_id": binding["input_id"],
                "receipt_sha256": copied_ref["sha256"], "source_sha256": digest})
    receipt_refs = [copied_ref]
    pending = []
    for split in ("development", "challenge", "oov"):
        splits[split] = []
        for row in panels[split]:
            digest = source_path(row["source_text"])
            raw = row["source_text"].encode()
            citation = "Authored decoder comparison: " + row["id"] if split != "oov" else "Unreviewed cached US Code span: " + row["id"]
            span = SourceSpan(SourceArtifact(digest, len(raw)), "diagnostic", plan_ref["sha256"],
                              row["id"], "en", citation, 0, len(raw), "identity")
            item = receipt_codec.EmbeddingInput(span, "diagnostic", str(len(pending)), row["source_text"], citation)
            candidate = {key: value for key, value in row.items() if split != "challenge" or key != "canonical_ir"}
            candidate["source_sha256"] = digest
            if "canonical_ir" in row:
                candidate["canonical_target_sha256"] = sha(canonical_bytes(row["canonical_ir"]))
            splits[split].append(candidate)
            pending.append((split, candidate, item))
    # Multiple dataset span identities may contain the same exact bytes (e.g.
    # citation fragments). Embed each unique source once and retain aliases.
    unique_inputs = {}
    for _, row, item in pending:
        unique_inputs.setdefault(row["source_sha256"], item)
    new_inputs = list(unique_inputs.values())
    produced = {}
    for offset in range(0, len(new_inputs), 128):
        batch = new_inputs[offset:offset + 128]
        receipt = producer.produce_native_embedding_receipt(batch, resolver=resolver, batch_size=16)
        receipt_ref = receipt.save(output / f"new-embedding-production-{offset // 128:03d}.json", resolver=resolver)
        reopened = receipt_codec.load_embedding_production_receipt(receipt_ref["path"],
            expected_sha256=receipt_ref["sha256"], expected_size_bytes=receipt_ref["bytes"], resolver=resolver)
        data = reopened.to_dict()
        if data["model"] != old_data["model"] or data["model_assets"] != old_data["model_assets"]:
            raise ValueError("new and reused embedding models differ")
        receipt_refs.append(receipt_ref)
        by_id = {row["input_id"]: row for row in data["results"]}
        for item in batch:
            result = by_id[item.input_id]
            produced[item.source.artifact.sha256] = (result, receipt_ref, item.input_id)
    for split, row, item in pending:
        result, receipt_ref, input_id = produced[row["source_sha256"]]
        row["embedding_status"] = result["status"]
        row["embedding"] = (list(struct.unpack(">384f", bytes.fromhex(result["vector"]["bits"])))
                            if result["status"] == "embedded" else None)
        if split != "oov" and row["embedding"] is None:
            raise ValueError("authored source did not receive a complete native embedding")
        bindings.append({"id": row["id"], "split": split, "input_id": input_id,
            "receipt_sha256": receipt_ref["sha256"], "source_sha256": row["source_sha256"],
            "reused_identical_source_bytes": input_id != item.input_id})
    for ref in (fixture_ref, prior_ref, queue_ref, plan_ref):
        verify_ref(ref)
    bindings_ref = save(output / "source-bindings.json", bindings)
    corpus = {"schema": "legal-decoder-comparison-corpus/v1", "label_origin": LABEL,
        "splits": splits, "frozen_plan": plan_ref, "sealed_targets": sealed_ref,
        "embedding_receipts": receipt_refs, "source_bindings": bindings_ref,
        "source_paths": source_paths, "model": old_data["model"], "model_assets": old_data["model_assets"],
        "embedding_reused_count": sum(len(splits[s]) for s in ORIGINAL_SPLITS),
        "embedding_new_count": len(new_inputs), "representation": "raw_l2_normalized_gte_small_384",
        "leakage_checks": leakage, "fixture": fixture_ref, "preparer": file_ref(__file__),
        "dataset": {"repository": queue["repository"], "revision": queue["revision"], "review_queue": queue_ref},
        "independently_reviewed": False, "training_executed": False, "qualified": False, "admitted": False,
        "preparation_seconds": time.monotonic() - started}
    corpus_ref = save(output / "corpus.json", corpus)
    summary = {"corpus": corpus_ref, "frozen_plan": plan_ref, "sealed_targets": sealed_ref,
               "split_counts": {key: len(value) for key, value in splits.items()}, "leakage_checks": leakage,
               "oov_codec_rejections": sum(row["source_codec_rejection"] is not None for row in splits["oov"]),
               "oov_embedding_statuses": dict(Counter(row["embedding_status"] for row in splits["oov"])),
               "preparation_seconds": corpus["preparation_seconds"]}
    save(output / "preparation-summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--prior-corpus", type=Path, default=PRIOR)
    parser.add_argument("--review-queue", type=Path, default=QUEUE)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.output_directory, fixture=args.fixture, prior_corpus=args.prior_corpus,
                             review_queue=args.review_queue), sort_keys=True))


if __name__ == "__main__":
    main()
