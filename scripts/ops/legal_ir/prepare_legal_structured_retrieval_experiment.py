#!/usr/bin/env python3
"""Freeze a larger authored value-held-out corpus for structured retrieval.

These synthetic targets are an explicit grammar diagnostic, not independently
reviewed legal semantics. Templates appeared in the previous experiment; only
entity/value novelty is claimed for the new challenge. No challenge canonical
targets or span annotations appear in inference inputs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_span_experiment as shared

ARTIFACTS = ROOT.parents[1] / "artifacts"
PREVIOUS = ARTIFACTS / "legal-decoder-proofbridge-20261002/prepared/corpus.json"
QUEUE = shared.QUEUE
LABEL = shared.LABEL
FIELDS = shared.FIELDS
canonical_bytes, sha, save = shared.canonical_bytes, shared.sha, shared.save
file_ref, verify_ref, formal_text = shared.file_ref, shared.verify_ref, shared.formal_text
NAMES = {
    "train": ("Aster", "Bramble", "Cypress", "Dahlia", "Elder", "Fennel", "Gardenia", "Hemlock",
              "Indigo", "Jacaranda", "Kalmia", "Lavender", "Magnolia", "Narcissus", "Olive", "Peony",
              "Quince", "Rosewood", "Saffron", "Tamarind", "Umber", "Verbena", "Willow", "Xenia",
              "Yarrow", "Zinnia", "Acacia", "Balsam", "Camellia", "Durian", "Eucalyptus", "Flax"),
    "tuning": ("Garnet", "Hickory", "Iberis", "Jasmine"),
    "challenge": ("Kudzu", "Lotus", "Myrtle", "Nutmeg", "Osier", "Primrose", "Redwood", "Sorrel"),
}
ACTIONS = {
    "train": ("inspect", "retain", "submit", "archive", "disclose", "review", "certify", "publish",
              "verify", "safeguard", "catalog", "transmit", "forward", "deliver", "secure", "preserve"),
    "tuning": ("inspect", "transmit", "collate", "catalog"),
    "challenge": ("authenticate", "release", "index", "digitize", "inspect", "retain", "certify", "deliver"),
}
ACTOR_SUFFIXES = ("Office", "Records Board", "County Records Office", "Regional Public Records Commission",
                  "Department of Archives", "Municipal Licensing Authority", "Public Information Review Tribunal", "Audit Unit")
OBJECTS = ("the {name} ledger", "the {name} permit file", "the quarterly {name} disclosure ledger",
           "the certified {name} financial statement", "the current {name} public accounts record",
           "the {name} historical correspondence file", "the local {name} licensing dossier",
           "the annual {name} compliance register")
CONDITIONS = ("the {name} permit is active", "the {name} license remains valid", "the {name} inspection has concluded",
              "the {name} certification is complete", "the {name} filing deadline has passed",
              "the {name} compliance test succeeds", "the {name} allocation is approved", "the {name} account is open")
EXCEPTIONS = ("the {name} alarm is active", "the {name} network is unavailable", "the {name} safety order applies",
              "the {name} emergency directive is in force", "the {name} office is closed",
              "the {name} authorization is suspended", "the {name} equipment has failed", "the {name} records are sealed")


def make_panels():
    panels = {}
    for split_index, (split, names) in enumerate(NAMES.items()):
        panels[split] = []
        for family_index, name in enumerate(names):
            index = family_index % 8
            values = {"actor": name + " " + ACTOR_SUFFIXES[index],
                      "action": ACTIONS[split][family_index % len(ACTIONS[split])],
                      "object": OBJECTS[index].format(name=name.lower()),
                      "conditions": CONDITIONS[index].format(name=name.lower()),
                      "exceptions": EXCEPTIONS[index].format(name=name.lower()),
                      "temporal": (f"within {413 + split_index * 100 + family_index} days" if family_index % 2 == 0 else
                                   f"before {2041 + split_index}-{family_index % 12 + 1:02d}-{family_index % 27 + 1:02d}"),
                      "citation": f"section {901 + split_index * 1000 + family_index}(c)"}
            family = "structured-" + split + "-" + name.lower()
            for template in range(8):
                offset = (family_index + 2 * (family_index // 8) if split == "train" else
                          2 + family_index if split == "tuning" else 3 + family_index)
                pattern = (template + offset) % 8
                for modality in ("O", "P", "F"):
                    text, ir = shared.render(values, template, pattern, modality)
                    panels[split].append({"id": f"{family}-t{template}-q{pattern}-{modality.lower()}",
                        "source_text": text, "canonical_ir": ir, "source_spans": shared.source_spans(text, ir),
                        "family_group": family, "template_id": template, "qualifier_pattern": pattern,
                        "source_sha256": sha(text.encode()), "canonical_target_sha256": sha(canonical_bytes(ir)),
                        "provenance": LABEL})
    check_panels(panels)
    return panels


def check_panels(panels):
    """Gold-construction checks; do not call this on sealed inference inputs."""
    old_panels = shared.make_panels()
    old_sources = {row["source_sha256"] for rows in old_panels.values() for row in rows}
    old_targets = {row["canonical_target_sha256"] for rows in old_panels.values() for row in rows}
    old_values = {field: set() for field in FIELDS}
    for rows in old_panels.values():
        for row in rows:
            rule = row["canonical_ir"]["rules"][0]
            for field in FIELDS:
                old_values[field].update([rule[field]] if field in FIELDS[:3] else rule[field])
    sources, targets, families, values, ids = {}, {}, {}, {}, set()
    split_values = {split: {field: set() for field in FIELDS} for split in panels}
    pair_counts, lengths = {}, {"actor": set(), "object": set()}
    maximum_tokens = 0
    for split, rows in panels.items():
        triples, pairs = {}, set()
        for row in rows:
            if row["id"] in ids:
                raise ValueError("duplicate row id")
            ids.add(row["id"])
            if row["source_sha256"] in old_sources or row["canonical_target_sha256"] in old_targets:
                raise ValueError("prior exposed source or target reused")
            if shared.source_spans(row["source_text"], row["canonical_ir"]) != row["source_spans"]:
                raise ValueError("source span annotation differs")
            if sha(row["source_text"].encode()) != row["source_sha256"] or sha(canonical_bytes(row["canonical_ir"])) != row["canonical_target_sha256"]:
                raise ValueError("source or target commitment differs")
            maximum_tokens = max(maximum_tokens, len(re.findall(r"\w+|[^\w\s]", row["source_text"])))
            normalized = " ".join(re.findall(r"\w+|[^\w\s]", row["source_text"].casefold()))
            for key, mapping, kind in ((normalized, sources, "source"), (row["canonical_target_sha256"], targets, "target"),
                                      (row["family_group"], families, "family")):
                if key in mapping and mapping[key] != split:
                    raise ValueError(kind + " crosses splits")
                mapping[key] = split
            rule = row["canonical_ir"]["rules"][0]
            for field in FIELDS:
                atoms = [rule[field]] if field in FIELDS[:3] else rule[field]
                split_values[split][field].update(atoms)
                for atom in atoms:
                    if field != "action":
                        if atom in old_values[field]:
                            raise ValueError("prior exposed canonical value reused")
                        if (field, atom) in values and values[(field, atom)] != split:
                            raise ValueError("canonical value crosses splits")
                        values[(field, atom)] = split
                if field in lengths:
                    lengths[field].add(len(rule[field].split()))
            pair = (row["template_id"], row["qualifier_pattern"])
            pairs.add(pair)
            triples.setdefault((row["family_group"], pair), set()).add(rule["modality"])
        if any(modalities != {"O", "P", "F"} for modalities in triples.values()):
            raise ValueError("modality triple incomplete")
        pair_counts[split] = len(pairs)
    if maximum_tokens > 256:
        raise ValueError("source exceeds decoder token ceiling")
    novelty = {split: {field: {"distinct_values": len(split_values[split][field]),
                             "unseen_in_current_train": len(split_values[split][field] - split_values["train"][field]),
                             "unseen_in_prior_experiment": len(split_values[split][field] - old_values[field])}
                       for field in FIELDS} for split in ("tuning", "challenge")}
    return {"prior_exposed_source_or_complete_target_overlap": 0,
            "prior_exposed_actor_object_qualifier_value_overlap": 0,
            "cross_split_source_target_family_overlap": 0, "cross_split_actor_object_qualifier_value_overlap": 0,
            "counterfactual_modalities_grouped": True, "exact_unique_nonoverlapping_spans": True,
            "source_token_maximum": maximum_tokens, "actor_word_lengths": sorted(lengths["actor"]),
            "object_word_lengths": sorted(lengths["object"]), "template_qualifier_pair_counts": pair_counts,
            "canonical_value_novelty": novelty, "globally_new_template_combinations_claimed": False}


def validate_inputs(corpus, challenge_targets_path):
    """Validate native bindings and frozen commitments without parsing targets."""
    if isinstance(corpus, (str, Path)):
        corpus = json.loads(Path(corpus).read_bytes())
    result = shared.validate_inputs(corpus, challenge_targets_path)
    plan = json.loads(verify_ref(corpus["frozen_plan"]))
    verify_ref(plan["shared_preparer"])
    if plan.get("experiment") != "structured-retrieval-expanded-values/v1":
        raise ValueError("structured retrieval experiment plan required")
    expected_counts = {"train": 768, "tuning": 96, "challenge": 192, "oov": 45}
    if plan["split_counts"] != expected_counts:
        raise ValueError("structured retrieval partition counts differ")
    previous = json.loads(verify_ref(corpus["previously_exposed_corpus"]))
    if plan["previously_exposed_corpus"] != corpus["previously_exposed_corpus"]:
        raise ValueError("previous exposure reference differs")
    old_sources, old_targets = set(), set()
    for split, rows in previous["splits"].items():
        if split == "oov":
            continue
        for row in rows:
            old_sources.add(row["source_sha256"])
            old_targets.add(row["canonical_target_sha256"])
    for split, rows in corpus["splits"].items():
        if split == "oov":
            continue
        for row in rows:
            if row["source_sha256"] in old_sources or row["canonical_target_sha256"] in old_targets:
                raise ValueError("prior exposed source or target reused")
    return {**result, "expanded_partition_counts_verified": True,
            "previously_exposed_source_target_overlap": 0, "challenge_target_json_parsed": False}


def prepare(output_directory, *, previous_corpus=PREVIOUS, review_queue=QUEUE):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as receipts
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan
    started = time.monotonic()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    previous_ref, queue_ref = file_ref(previous_corpus), file_ref(review_queue)
    panels = make_panels()
    leakage = check_panels(panels)
    panels["oov"] = shared.observed_panel(json.loads(verify_ref(queue_ref)))
    plan = {"schema": "legal-span-experiment-frozen-plan/v1", "experiment": "structured-retrieval-expanded-values/v1",
        "created_at": datetime.now(timezone.utc).isoformat(), "preparer": file_ref(__file__),
        "shared_preparer": file_ref(shared.__file__), "previously_exposed_corpus": previous_ref,
        "review_queue": queue_ref, "label_origin": LABEL, "leakage_checks": leakage,
        "split_counts": {key: len(rows) for key, rows in panels.items()},
        "rows": [{"id": row["id"], "split": split, "source_sha256": row["source_sha256"],
                  "canonical_target_sha256": row.get("canonical_target_sha256"), "family_group": row.get("family_group"),
                  "template_id": row.get("template_id"), "qualifier_pattern": row.get("qualifier_pattern")}
                 for split, rows in panels.items() for row in rows],
        "policy": {"fit": ["train"], "selection": ["tuning"], "sealed_final_evaluation": ["challenge"],
            "formal_embedding_splits": ["train"], "source_embedding_splits": list(panels),
            "train_retrieval_exclude": "entire query family_group", "model_consulted_for_row_selection": False,
            "fixed_before_embedding_and_training": True, "independently_reviewed": False,
            "formal_serialization": "sorted compact ASCII JSON of canonical_ir",
            "novelty": "all actor/object/qualifier values absent from prior experiment; four challenge actions absent from current training",
            "grammar_scope": "all eight templates and all64 template/qualifier combinations occur in current training; grammar is previously exposed",
            "sealed_meaning": "Separate targets provide procedural isolation, not a security boundary",
            "oov": "Repeated target-free observations from the same pinned USCode cache; no semantic scoring"}}
    plan_ref = save(output / "frozen-plan.json", plan)
    sealed_ref = save(output / "sealed-evaluation-targets.json", {"schema": "legal-span-experiment-sealed-targets/v1",
        "split": "challenge", "frozen_plan": plan_ref,
        "targets": [{key: row[key] for key in ("id", "canonical_ir", "source_spans", "source_sha256", "canonical_target_sha256")}
                    for row in panels["challenge"]]})
    panels["challenge"] = [{key: value for key, value in row.items() if key not in {"canonical_ir", "source_spans"}}
                           for row in panels["challenge"]]
    source_dir = output / "sources"
    source_dir.mkdir()
    paths, requests = {}, []
    for split, rows in panels.items():
        for row in rows:
            texts = [("source", row["source_text"])]
            if split == "train":
                texts.append(("formal", formal_text(row["canonical_ir"])))
            for role, text in texts:
                raw, digest = text.encode(), sha(text.encode())
                if digest not in paths:
                    path = source_dir / (digest + ".txt")
                    with path.open("xb") as stream:
                        stream.write(raw)
                    paths[digest] = str(path)
                citation = f"Authored structured retrieval {role}: {row['id']}" if split != "oov" else f"Unreviewed USCode source: {row['id']}"
                source = SourceSpan(SourceArtifact(digest, len(raw)), "diagnostic", plan_ref["sha256"],
                                    row["id"] + "-" + role, "en", citation, 0, len(raw), "identity")
                item = receipts.EmbeddingInput(source, "diagnostic", str(len(requests)), text, citation)
                requests.append((split, row, role, item))
    def resolver(ref):
        path = Path(paths[ref["sha256"]])
        raw = path.read_bytes()
        if sha(raw) != ref["sha256"] or len(raw) != ref["bytes"]:
            raise ValueError("native embedding source changed")
        return path
    unique = {}
    for _, _, role, item in requests:
        unique.setdefault((role, item.source.artifact.sha256), item)
    produced, receipt_refs, model_data = {}, [], None
    for role in ("source", "formal"):
        all_inputs = [item for (item_role, _), item in unique.items() if item_role == role]
        for offset in range(0, len(all_inputs), 128):
            batch = all_inputs[offset:offset + 128]
            native = producer.produce_native_embedding_receipt(batch, resolver=resolver, batch_size=16)
            ref = native.save(output / f"{role}-embedding-production-{offset // 128:03d}.json", resolver=resolver)
            data = receipts.load_embedding_production_receipt(ref["path"], expected_sha256=ref["sha256"],
                expected_size_bytes=ref["bytes"], resolver=resolver).to_dict()
            if model_data is not None and (data["model"] != model_data["model"] or data["model_assets"] != model_data["model_assets"]):
                raise ValueError("native embedding model changed")
            model_data = data
            receipt_refs.append({"role": role, **ref})
            by_id = {result["input_id"]: result for result in data["results"]}
            for item in batch:
                produced[(role, item.source.artifact.sha256)] = (by_id[item.input_id], ref, item.input_id)
            print(json.dumps({"role": role, "completed": min(offset + 128, len(all_inputs)), "total": len(all_inputs)}), flush=True)
    bindings = []
    for split, row, role, item in requests:
        result, ref, input_id = produced[(role, item.source.artifact.sha256)]
        vector = list(struct.unpack(">384f", bytes.fromhex(result["vector"]["bits"]))) if result["status"] == "embedded" else None
        key = "embedding" if role == "source" else "formal_embedding"
        row[key], row[key + "_status"] = vector, result["status"]
        if split != "oov" and vector is None:
            raise ValueError("authored input lacks complete native embedding")
        bindings.append({"id": row["id"], "split": split, "role": role, "input_id": input_id,
                         "receipt_sha256": ref["sha256"], "text_sha256": item.source.artifact.sha256})
    bindings_ref = save(output / "embedding-bindings.json", bindings)
    corpus = {"schema": "legal-span-experiment-corpus/v1", "experiment": plan["experiment"], "splits": panels,
        "frozen_plan": plan_ref, "sealed_targets": sealed_ref, "embedding_receipts": receipt_refs,
        "embedding_bindings": bindings_ref, "source_paths": paths, "model": model_data["model"],
        "model_assets": model_data["model_assets"], "representation": "raw_l2_normalized_gte_small_384",
        "formal_representation": "canonical_json_gte_small_384_train_only", "label_origin": LABEL,
        "leakage_checks": leakage, "preparer": file_ref(__file__), "previously_exposed_corpus": previous_ref,
        "dataset": {"repository": "justicedao/uscode-autoformal-span-cache", "revision": shared.REVISION, "review_queue": queue_ref},
        "independently_reviewed": False, "training_executed": False, "qualified": False, "admitted": False,
        "preparation_seconds": time.monotonic() - started}
    corpus_ref = save(output / "corpus.json", corpus)
    validation = validate_inputs(corpus, sealed_ref["path"])
    summary = {"corpus": corpus_ref, "frozen_plan": plan_ref, "sealed_targets": sealed_ref,
               "split_counts": plan["split_counts"], "validation": validation, "leakage_checks": leakage,
               "source_embedding_count": sum(len(rows) for rows in panels.values()), "formal_embedding_count": len(panels["train"]),
               "native_receipts": len(receipt_refs), "preparation_seconds": corpus["preparation_seconds"]}
    save(output / "preparation-summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--previous-corpus", type=Path, default=PREVIOUS)
    parser.add_argument("--review-queue", type=Path, default=QUEUE)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.output_directory, previous_corpus=args.previous_corpus, review_queue=args.review_queue), sort_keys=True))


if __name__ == "__main__":
    main()
