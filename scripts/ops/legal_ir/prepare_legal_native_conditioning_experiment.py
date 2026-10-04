#!/usr/bin/env python3
"""Fresh value-family panel and reusable native source embeddings, without gold leakage."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_span_experiment as shared

ARTIFACTS = ROOT.parents[1] / "artifacts"
PREVIOUS = ARTIFACTS / "legal-decoder-structured-retrieval-20261002/prepared/corpus.json"
NAMES = {
    "train": ("Aspen", "Bellflower", "Chestnut", "Dandelion", "Gentian", "Hawthorn", "Lupine", "Mimosa",
              "Oleander", "Pansy", "Rhododendron", "Snowdrop", "Thistle", "Tulip", "Violet", "Wisteria"),
    "tuning": ("Begonia", "Calendula", "Freesia", "Hellebore"),
    "challenge": ("Bluebell", "Crocus", "Foxglove", "Hyacinth", "Marigold", "Nasturtium", "Petunia", "Snapdragon"),
}
SUFFIXES = ("Authority", "Regional Board", "Public Records Commission", "District Public Information Review Board",
            "Office of Public Records", "Regional Office of Municipal Accounts",
            "Department of Historical Archives and Records", "Municipal Information Tribunal")
ACTIONS = ("inspect", "retain", "submit", "archive", "disclose", "review", "certify", "publish")


def make_panels(previous):
    panels = {"train": copy.deepcopy(previous["splits"]["train"]), "tuning": [], "challenge": []}
    old_sources = {r["source_sha256"] for split, rows in previous["splits"].items() if split != "oov" for r in rows}
    old_targets = {r["canonical_target_sha256"] for split, rows in previous["splits"].items() if split != "oov" for r in rows}
    for row in panels["train"]:
        for key in ("formal_embedding", "formal_embedding_status"):
            row.pop(key, None)
    fresh_hashes = set()
    for split_index, (split, names) in enumerate(NAMES.items()):
        for index, name in enumerate(names):
            lower = name.lower()
            values = {"actor": name + " " + SUFFIXES[index % len(SUFFIXES)], "action": ACTIONS[index % 8],
                "object": "the certified " + lower + " public register",
                "conditions": "the " + lower + " registration application has been accepted",
                "exceptions": "the " + lower + " preservation notice remains effective",
                "temporal": (f"within {1101 + 100 * split_index + index} days" if index % 2 == 0 else
                             f"before {2071 + split_index}-{index % 12 + 1:02d}-{index % 27 + 1:02d}"),
                "citation": f"section {8001 + split_index * 100 + index}(d)"}
            family = f"native-{split}-{lower}"
            for template in range(8):
                pattern = (template + index) % 8
                for modality in ("O", "P", "F"):
                    text, ir = shared.render(values, template, pattern, modality)
                    source_hash, target_hash = shared.sha(text.encode()), shared.sha(shared.canonical_bytes(ir))
                    if source_hash in old_sources or target_hash in old_targets or source_hash in fresh_hashes:
                        raise ValueError("new source/target family overlaps previous exposure or itself")
                    fresh_hashes.add(source_hash)
                    panels[split].append({"id": f"{family}-t{template}-q{pattern}-{modality.lower()}",
                        "source_text": text, "canonical_ir": ir, "source_spans": shared.source_spans(text, ir),
                        "family_group": family, "template_id": template, "qualifier_pattern": pattern,
                        "source_sha256": source_hash, "canonical_target_sha256": target_hash,
                        "provenance": shared.LABEL})
    groups, atoms, ids = {}, {}, set()
    for split, rows in panels.items():
        for row in rows:
            if row["id"] in ids:
                raise ValueError("duplicate input id")
            ids.add(row["id"])
            key = row["family_group"]
            if key in groups and groups[key] != split:
                raise ValueError("family overlap")
            groups[key] = split
            for facet in ("actor", "object", "conditions", "exceptions", "temporal"):
                rule = row["canonical_ir"]["rules"][0]
                values = [rule[facet]] if facet in ("actor", "object") else rule[facet]
                for value in values:
                    key = (facet, value)
                    if key in atoms and atoms[key] != split:
                        raise ValueError("cross-split value overlap")
                    atoms[key] = split
    return panels


def prepare(output_directory, *, previous_corpus=PREVIOUS):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as receipts
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan
    started = time.monotonic()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    previous_ref = shared.file_ref(previous_corpus)
    previous = json.loads(shared.verify_ref(previous_ref))
    panels = make_panels(previous)
    panels["oov"] = copy.deepcopy(previous["splits"]["oov"])
    plan = {"schema": "legal-native-conditioning-plan/v1", "previous": previous_ref,
        "preparer": shared.file_ref(__file__), "rendering": shared.file_ref(shared.__file__),
        "counts": {split: len(rows) for split, rows in panels.items()},
        "old_training_rows_reused": len(previous["splits"]["train"]),
        "new_training_rows": 384, "new_tuning_rows": 96, "new_challenge_rows": 192,
        "label_origin": shared.LABEL, "reviewed_statutory_gold": False,
        "grammar_scope": "Previously exposed templates, new actor/qualifier values; actor lengths reach7words.",
        "rows": [{"id": r["id"], "split": split, "source_sha256": r["source_sha256"],
                  "canonical_target_sha256": r.get("canonical_target_sha256"), "family_group": r.get("family_group")}
                 for split, rows in panels.items() for r in rows]}
    plan_ref = shared.save(output / "frozen-plan.json", plan)
    targets_ref = shared.save(output / "sealed-evaluation-targets.json", {
        "schema": "legal-span-experiment-sealed-targets/v1", "frozen_plan": plan_ref,
        "targets": [{k: r[k] for k in ("id", "canonical_ir", "source_spans", "source_sha256", "canonical_target_sha256")}
                    for r in panels["challenge"]]})
    panels["challenge"] = [{k: v for k, v in r.items() if k not in ("canonical_ir", "source_spans")}
                           for r in panels["challenge"]]
    source_dir = output / "sources"
    source_dir.mkdir()
    paths = dict(previous["source_paths"])
    receipt_refs = [r for r in previous["embedding_receipts"] if r["role"] == "source"]
    bindings = [r for r in json.loads(shared.verify_ref(previous["embedding_bindings"]))
                if r["role"] == "source" and r["split"] in ("train", "oov")]
    requests = []
    for split, rows in panels.items():
        for row in rows:
            if row.get("embedding_status") == "embedded":
                continue
            raw, key = row["source_text"].encode(), row["source_sha256"]
            path = source_dir / (key + ".txt")
            with path.open("xb") as stream:
                stream.write(raw)
            paths[key] = str(path)
            citation = "Authored native conditioning: " + row["id"]
            source = SourceSpan(SourceArtifact(key, len(raw)), "diagnostic", plan_ref["sha256"],
                                row["id"], "en", citation, 0, len(raw), "identity")
            requests.append((split, row, receipts.EmbeddingInput(source, "diagnostic", str(len(requests)), row["source_text"], citation)))
    def resolver(ref):
        path = Path(paths[ref["sha256"]])
        raw = path.read_bytes()
        if shared.sha(raw) != ref["sha256"] or len(raw) != ref["bytes"]:
            raise ValueError("embedding source binding differs")
        return path
    for start in range(0, len(requests), 128):
        batch = requests[start:start + 128]
        produced = producer.produce_native_embedding_receipt([r[2] for r in batch], resolver=resolver, batch_size=16)
        ref = produced.save(output / f"source-production-{start // 128:03d}.json", resolver=resolver)
        data = receipts.load_embedding_production_receipt(ref["path"], expected_sha256=ref["sha256"],
            expected_size_bytes=ref["bytes"], resolver=resolver).to_dict()
        if data["model"] != previous["model"] or data["model_assets"] != previous["model_assets"]:
            raise ValueError("native encoder or assets differ from reused embeddings")
        receipt_refs.append({"role": "source", **ref})
        results = {r["input_id"]: r for r in data["results"]}
        for split, row, item in batch:
            result = results[item.input_id]
            if result["status"] != "embedded":
                raise ValueError("new authored source must have a native embedding")
            row["embedding"] = list(struct.unpack(">384f", bytes.fromhex(result["vector"]["bits"])))
            row["embedding_status"] = "embedded"
            bindings.append({"id": row["id"], "split": split, "role": "source", "input_id": item.input_id,
                             "receipt_sha256": ref["sha256"], "text_sha256": row["source_sha256"]})
        print(json.dumps({"embedded_new": min(start + 128, len(requests)), "new_total": len(requests)}), flush=True)
    corpus = {"schema": "legal-native-conditioning-corpus/v1", "splits": panels, "frozen_plan": plan_ref,
        "sealed_targets": targets_ref, "previous": previous_ref, "embedding_receipts": receipt_refs,
        "embedding_bindings": shared.save(output / "embedding-bindings.json", bindings), "source_paths": paths,
        "model": previous["model"], "model_assets": previous["model_assets"],
        "source_embedding_stage": "native_gte_small_384", "target_embeddings_generated": False,
        "qualified": False, "independently_reviewed": False, "seconds": time.monotonic() - started}
    ref = shared.save(output / "corpus.json", corpus)
    shared.save(output / "summary.json", {"corpus": ref, "counts": plan["counts"],
        "new_encoder_rows": len(requests), "reused_rows": sum(len(r) for r in panels.values()) - len(requests),
        "sealed_targets": targets_ref, "seconds": corpus["seconds"]})
    return ref


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--previous-corpus", default=str(PREVIOUS))
    args = parser.parse_args()
    print(json.dumps(prepare(args.output_directory, previous_corpus=args.previous_corpus)))
