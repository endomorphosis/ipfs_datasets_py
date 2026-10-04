#!/usr/bin/env python3
"""Freeze authored source-span diagnostics and target-free retrieval inputs.

This is a controlled grammar experiment, not a reviewed statutory gold set.
Challenge targets are stored separately before any embedding or model training.
Only training canonical targets receive formal-side embeddings.
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
ARTIFACTS = ROOT.parents[1] / "artifacts"
QUEUE = ARTIFACTS / "legal-decoder-pilot-20261002/review-queue.json"
LABEL = "authored_synthetic_not_legal_authority"
REVISION = "765176c6db79ba65c1697c21dead43666350b730"
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
NAMES = {
    "train": ("Alder", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Ginkgo", "Hazel", "Iris", "Jade", "Holly", "Laurel"),
    "tuning": ("Juniper", "Kestrel"),
    "challenge": ("Larch", "Maple", "Nettle", "Orchid", "Poplar", "Quartz", "Rowan", "Spruce"),
}
ACTIONS = {
    "train": ("inspect", "retain", "submit", "archive", "disclose", "review"),
    "tuning": ("inspect", "catalog"),
    "challenge": ("inspect", "retain", "certify", "publish", "verify", "safeguard", "submit", "archive"),
}
PATTERNS = ((), ("conditions",), ("exceptions",), ("temporal",),
            ("conditions", "exceptions"), ("conditions", "temporal"),
            ("exceptions", "temporal"), ("conditions", "exceptions", "temporal"))
MODALS = (
    {"O": "shall", "P": "may", "F": "shall not"},
    {"O": "must", "P": "is allowed to", "F": "must not"},
    {"O": "has a duty to", "P": "has permission to", "F": "is forbidden to"},
    {"O": "is required to", "P": "is permitted to", "F": "is not permitted to"},
)


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def formal_text(ir):
    """The fixed formal-side input: canonical JSON, with no natural source text."""
    return canonical_bytes(ir).decode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


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
    if sha(raw) != ref["sha256"] or len(raw) != ref["bytes"]:
        raise ValueError("artifact content differs from recorded reference")
    return raw


def source_spans(text, ir):
    """Require each canonical value to be one unique complete-token substring."""
    rules = ir.get("rules")
    if not isinstance(rules, list) or len(rules) != 1:
        raise ValueError("one canonical rule required")
    rule = rules[0]
    if set(rule) != {"modality", *FIELDS} or rule["modality"] not in {"O", "P", "F"}:
        raise ValueError("closed deontic rule required")
    tokens = list(re.finditer(r"\w+|[^\w\s]", text, flags=re.UNICODE))
    starts, ends = {m.start() for m in tokens}, {m.end() for m in tokens}
    result = {}
    occupied = []
    for field in FIELDS:
        values = [rule[field]] if field in FIELDS[:3] else rule[field]
        if not isinstance(values, list) or len(values) > 1 or (field in FIELDS[:3] and not values):
            raise ValueError("at most one span per canonical field required")
        spans = []
        for value in values:
            if not isinstance(value, str) or not value:
                raise ValueError("nonempty canonical source slice required")
            occurrences = [m.span() for m in re.finditer(re.escape(value), text)]
            if len(occurrences) != 1:
                raise ValueError("canonical source slice must occur exactly once")
            start, end = occurrences[0]
            if start not in starts or end not in ends:
                raise ValueError("canonical source slice must be token aligned")
            if any(start < old_end and old_start < end for old_start, old_end in occupied):
                raise ValueError("canonical source spans must not overlap")
            occupied.append((start, end))
            spans.append([start, end])
        result[field] = spans[0] if field in FIELDS[:3] else spans
    return result


def render(values, template, pattern, modality):
    present = set(PATTERNS[pattern])
    condition, exception, temporal = (values[key] for key in FIELDS[3:])
    rule = {"modality": modality, **{key: values[key] for key in FIELDS[:3]},
            **{key: [values[key]] if key in present else [] for key in FIELDS[3:]}}
    prefix = ""
    order = ("conditions", "exceptions", "temporal")
    citation = values["citation"]
    if template == 1:
        order = ("temporal", "exceptions", "conditions")
    elif template == 2:
        prefix = f"Under {citation}, "
        order = ("conditions", "temporal", "exceptions")
    elif template == 3:
        prefix = f"For purposes of {citation}, "
        order = ("exceptions", "conditions", "temporal")
    elif template == 4:
        if "conditions" in present:
            prefix = f"If {condition}, "
            present.remove("conditions")
        else:
            prefix = f"Pursuant to {citation}, "
        order = ("exceptions", "temporal", "conditions")
    elif template == 5:
        if "exceptions" in present:
            prefix = f"Unless {exception}, "
            present.remove("exceptions")
        else:
            prefix = f"Under {citation}, "
        order = ("temporal", "conditions", "exceptions")
    elif template == 6:
        prefix = f"As provided in {citation}, "
        order = ("temporal", "conditions", "exceptions")
    elif template == 7:
        prefix = f"For the administration of {citation}, "
        order = ("exceptions", "temporal", "conditions")
    text = f"{prefix}{values['actor']} {MODALS[template % 4][modality]} {values['action']} {values['object']}"
    for field in order:
        if field in present:
            text += {"conditions": f" if {condition}", "exceptions": f" unless {exception}",
                     "temporal": f" {temporal}"}[field]
    return text + ".", {"rules": [rule]}


def make_panels():
    panels = {}
    for split_index, (split, names) in enumerate(NAMES.items()):
        panels[split] = []
        for family_index, name in enumerate(names):
            offset = split_index * 100
            values = {
                "actor": f"{name} County Records Office",
                "action": ACTIONS[split][family_index % len(ACTIONS[split])],
                "object": f"the {name.lower()} audit register",
                "conditions": f"the {name.lower()} permit is active",
                "exceptions": f"the {name.lower()} alarm is active",
                "temporal": (f"within {13 + offset + family_index} days" if family_index % 2 == 0 else
                             f"before {2031 + split_index}-{family_index % 12 + 1:02d}-{family_index % 10 + 11:02d}"),
                "citation": f"section {101 + offset + family_index}(b)",
            }
            family = f"span-{split}-{name.lower()}"
            for template in range(8):
                pattern = (template + (family_index % 6 if split == "train" else
                                      2 + family_index if split == "tuning" else 6 + family_index % 2)) % 8
                for modality in ("O", "P", "F"):
                    text, ir = render(values, template, pattern, modality)
                    panels[split].append({"id": f"{family}-t{template}-q{pattern}-{modality.lower()}",
                        "source_text": text, "canonical_ir": ir, "source_spans": source_spans(text, ir),
                        "family_group": family, "template_id": template, "qualifier_pattern": pattern,
                        "source_sha256": sha(text.encode()), "canonical_target_sha256": sha(canonical_bytes(ir)),
                        "provenance": LABEL})
    check_panels(panels)
    return panels


def check_panels(panels):
    seen_ids, sources, targets, groups, values = set(), {}, {}, {}, {}
    template_patterns = {}
    for split, rows in panels.items():
        template_patterns[split] = set()
        triples = {}
        for row in rows:
            if row["id"] in seen_ids:
                raise ValueError("duplicate row id")
            seen_ids.add(row["id"])
            source_key = " ".join(re.findall(r"\w+|[^\w\s]", row["source_text"].casefold()))
            for key, table, kind in ((source_key, sources, "source"),
                                      (sha(canonical_bytes(row["canonical_ir"])), targets, "complete target"),
                                      (row["family_group"], groups, "family group")):
                if key in table and table[key] != split:
                    raise ValueError(kind + " overlaps splits")
                table[key] = split
            if source_spans(row["source_text"], row["canonical_ir"]) != row["source_spans"]:
                raise ValueError("span annotations differ from exact source")
            if sha(row["source_text"].encode()) != row["source_sha256"]:
                raise ValueError("source hash mismatch")
            if sha(canonical_bytes(row["canonical_ir"])) != row["canonical_target_sha256"]:
                raise ValueError("target hash mismatch")
            rule = row["canonical_ir"]["rules"][0]
            for field in ("actor", "object", "conditions", "exceptions", "temporal"):
                atoms = [rule[field]] if field in {"actor", "object"} else rule[field]
                for atom in atoms:
                    key = (field, atom)
                    if key in values and values[key] != split:
                        raise ValueError("canonical value overlaps splits")
                    values[key] = split
            pair = (row["template_id"], row["qualifier_pattern"])
            template_patterns[split].add(pair)
            triples.setdefault((row["family_group"], pair), set()).add(rule["modality"])
        if any(modalities != {"O", "P", "F"} for modalities in triples.values()):
            raise ValueError("modality counterfactual triple is incomplete")
    if template_patterns["challenge"] & (template_patterns["train"] | template_patterns["tuning"]):
        raise ValueError("challenge template/qualifier pair overlaps fit or tuning")
    train_values = {field: set() for field in FIELDS}
    for row in panels["train"]:
        rule = row["canonical_ir"]["rules"][0]
        for field in FIELDS:
            train_values[field].update([rule[field]] if field in FIELDS[:3] else rule[field])
    novelty = {}
    for split in ("tuning", "challenge"):
        novelty[split] = {}
        for field in FIELDS:
            observed = set()
            for row in panels[split]:
                value = row["canonical_ir"]["rules"][0][field]
                observed.update([value] if field in FIELDS[:3] else value)
            novelty[split][field] = {"distinct_values": len(observed),
                                    "unseen_in_train": len(observed - train_values[field])}
    return {"cross_split_source_overlap": 0, "cross_split_complete_target_overlap": 0,
            "cross_split_family_overlap": 0, "cross_split_actor_object_qualifier_value_overlap": 0,
            "challenge_template_qualifier_pair_overlap": 0, "counterfactual_triples_grouped": True,
            "unique_token_aligned_nonoverlapping_spans": True,
            "template_qualifier_pairs": {key: len(value) for key, value in template_patterns.items()},
            "canonical_value_novelty": novelty}


def observed_panel(queue):
    if queue.get("repository") != "justicedao/uscode-autoformal-span-cache" or queue.get("revision") != REVISION:
        raise ValueError("observations require pinned dataset revision")
    rows = []
    for item in queue["entries"]:
        if len(item["source_text_variants"]) != 1 or not item["source_text_consistent_across_occurrences"]:
            raise ValueError("observation must identify one exact source")
        text = item["source_text_variants"][0]
        rows.append({"id": item["source_span_id"], "source_text": text, "source_sha256": sha(text.encode()),
                     "legal_ids": item["legal_ids"], "provenance": "unreviewed_dataset_observation",
                     "target_available": False, "training_qualified": False})
    return rows


def prepare(output_directory, *, review_queue=QUEUE):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as receipts
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan
    started = time.monotonic()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    queue_ref = file_ref(review_queue)
    panels = make_panels()
    leakage = check_panels(panels)
    panels["oov"] = observed_panel(json.loads(verify_ref(queue_ref)))
    plan = {"schema": "legal-span-experiment-frozen-plan/v1", "created_at": datetime.now(timezone.utc).isoformat(),
            "preparer": file_ref(__file__), "review_queue": queue_ref, "label_origin": LABEL,
            "split_counts": {key: len(rows) for key, rows in panels.items()}, "leakage_checks": leakage,
            "rows": [{"id": row["id"], "split": split, "source_sha256": row["source_sha256"],
                      "canonical_target_sha256": row.get("canonical_target_sha256"),
                      "family_group": row.get("family_group"), "template_id": row.get("template_id"),
                      "qualifier_pattern": row.get("qualifier_pattern")}
                     for split, rows in panels.items() for row in rows],
            "policy": {"fit": ["train"], "selection": ["tuning"], "sealed_final_evaluation": ["challenge"],
                       "formal_embedding_splits": ["train"], "source_embedding_splits": list(panels),
                       "formal_serialization": "sorted compact ASCII JSON of canonical_ir",
                       "train_retrieval_exclude": "entire query family_group",
                       "model_consulted_for_selection": False, "fixed_before_embedding_and_training": True,
                       "independently_reviewed": False,
                       "sealed_meaning": "Separate targets provide procedural isolation, not a security boundary",
                       "novelty": "Disjoint actor/object/qualifier values and challenge-only template/qualifier combinations",
                       "oov": "Observed sources without inferred canonical targets or semantic scores"}}
    plan_ref = save(output / "frozen-plan.json", plan)
    sealed_ref = save(output / "sealed-evaluation-targets.json", {
        "schema": "legal-span-experiment-sealed-targets/v1", "split": "challenge", "frozen_plan": plan_ref,
        "targets": [{key: row[key] for key in ("id", "canonical_ir", "source_spans", "source_sha256", "canonical_target_sha256")}
                    for row in panels["challenge"]]})
    panels["challenge"] = [{key: value for key, value in row.items() if key not in {"canonical_ir", "source_spans"}}
                           for row in panels["challenge"]]
    source_dir = output / "sources"
    source_dir.mkdir()
    paths, requests = {}, []
    for split, rows in panels.items():
        for row in rows:
            for role, text in [("source", row["source_text"])] + (
                    [("formal", formal_text(row["canonical_ir"]))] if split == "train" else []):
                raw = text.encode()
                digest = sha(raw)
                if digest not in paths:
                    path = source_dir / (digest + ".txt")
                    with path.open("xb") as stream:
                        stream.write(raw)
                    paths[digest] = str(path)
                citation = f"Authored span diagnostic {role}: {row['id']}" if split != "oov" else f"Unreviewed USCode source: {row['id']}"
                span = SourceSpan(SourceArtifact(digest, len(raw)), "diagnostic", plan_ref["sha256"],
                                  row["id"] + "-" + role, "en", citation, 0, len(raw), "identity")
                item = receipts.EmbeddingInput(span, "diagnostic", str(len(requests)), text, citation)
                requests.append((split, row, role, item))
    def resolver(ref):
        path = Path(paths[ref["sha256"]])
        raw = path.read_bytes()
        if sha(raw) != ref["sha256"] or len(raw) != ref["bytes"]:
            raise ValueError("embedding source bytes changed")
        return path
    unique = {}
    for _, _, role, item in requests:
        unique.setdefault((role, item.source.artifact.sha256), item)
    produced, receipt_refs, model_data = {}, [], None
    # Separate source and formal receipts make the train-only target boundary auditable.
    for role in ("source", "formal"):
        batch_inputs = [item for (item_role, _), item in unique.items() if item_role == role]
        for offset in range(0, len(batch_inputs), 128):
            batch = batch_inputs[offset:offset + 128]
            receipt = producer.produce_native_embedding_receipt(batch, resolver=resolver, batch_size=16)
            ref = receipt.save(output / f"{role}-embedding-production-{offset // 128:03d}.json", resolver=resolver)
            data = receipts.load_embedding_production_receipt(ref["path"], expected_sha256=ref["sha256"],
                expected_size_bytes=ref["bytes"], resolver=resolver).to_dict()
            if model_data is not None and (data["model"] != model_data["model"] or data["model_assets"] != model_data["model_assets"]):
                raise ValueError("embedding model changed between batches")
            model_data = data
            receipt_refs.append({"role": role, **ref})
            by_id = {item["input_id"]: item for item in data["results"]}
            for item in batch:
                produced[(role, item.source.artifact.sha256)] = (by_id[item.input_id], ref, item.input_id)
            print(json.dumps({"role": role, "completed": min(offset + 128, len(batch_inputs)),
                              "total": len(batch_inputs)}), flush=True)
    bindings = []
    for split, row, role, item in requests:
        result, ref, input_id = produced[(role, item.source.artifact.sha256)]
        vector = list(struct.unpack(">384f", bytes.fromhex(result["vector"]["bits"]))) if result["status"] == "embedded" else None
        key = "embedding" if role == "source" else "formal_embedding"
        row[key], row[key + "_status"] = vector, result["status"]
        if split != "oov" and vector is None:
            raise ValueError("authored input did not receive a native embedding")
        bindings.append({"id": row["id"], "split": split, "role": role, "input_id": input_id,
                         "receipt_sha256": ref["sha256"], "text_sha256": item.source.artifact.sha256})
    bindings_ref = save(output / "embedding-bindings.json", bindings)
    corpus = {"schema": "legal-span-experiment-corpus/v1", "splits": panels, "frozen_plan": plan_ref,
        "sealed_targets": sealed_ref, "embedding_receipts": receipt_refs, "embedding_bindings": bindings_ref,
        "source_paths": paths, "model": model_data["model"], "model_assets": model_data["model_assets"],
        "representation": "raw_l2_normalized_gte_small_384", "formal_representation": "canonical_json_gte_small_384_train_only",
        "label_origin": LABEL, "leakage_checks": leakage, "preparer": file_ref(__file__),
        "dataset": {"repository": "justicedao/uscode-autoformal-span-cache", "revision": REVISION, "review_queue": queue_ref},
        "independently_reviewed": False, "training_executed": False, "qualified": False, "admitted": False,
        "preparation_seconds": time.monotonic() - started}
    corpus_ref = save(output / "corpus.json", corpus)
    validation = validate_inputs(corpus, sealed_ref["path"])
    summary = {"corpus": corpus_ref, "frozen_plan": plan_ref, "sealed_targets": sealed_ref,
               "split_counts": plan["split_counts"], "validation": validation,
               "source_embedding_count": sum(len(rows) for rows in panels.values()),
               "formal_embedding_count": len(panels["train"]), "preparation_seconds": corpus["preparation_seconds"]}
    save(output / "preparation-summary.json", summary)
    return summary


def validate_inputs(corpus, challenge_targets_path):
    """Verify source/formal receipts and visible targets; never parse sealed JSON."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as receipts
    if isinstance(corpus, (str, Path)):
        corpus = json.loads(Path(corpus).read_bytes())
    if corpus.get("schema") != "legal-span-experiment-corpus/v1":
        raise ValueError("unsupported span corpus schema")
    plan = json.loads(verify_ref(corpus["frozen_plan"]))
    verify_ref(corpus["preparer"])
    verify_ref(plan["preparer"])
    verify_ref(corpus["dataset"]["review_queue"])
    sealed = corpus["sealed_targets"]
    if Path(challenge_targets_path).resolve() != Path(sealed["path"]).resolve():
        raise ValueError("sealed target path differs")
    verify_ref(sealed)  # Bytes/hash only. No target JSON is inspected here.
    planned = {row["id"]: row for row in plan["rows"]}
    if len(planned) != len(plan["rows"]):
        raise ValueError("duplicate planned id")
    def resolver(ref):
        path = Path(corpus["source_paths"][ref["sha256"]])
        raw = path.read_bytes()
        if sha(raw) != ref["sha256"] or len(raw) != ref["bytes"]:
            raise ValueError("embedding artifact bytes changed")
        return path
    native, native_inputs, receipt_roles = {}, {}, {}
    for ref in corpus["embedding_receipts"]:
        data = receipts.load_embedding_production_receipt(ref["path"], expected_sha256=ref["sha256"],
            expected_size_bytes=ref["bytes"], resolver=resolver).to_dict()
        if data["model"] != corpus["model"] or data["model_assets"] != corpus["model_assets"]:
            raise ValueError("native embedding provenance differs")
        receipt_roles[ref["sha256"]] = ref["role"]
        for item in data["inputs"]:
            native_inputs[(ref["sha256"], item["input_id"])] = item
        for result in data["results"]:
            native[(ref["sha256"], result["input_id"])] = result
    bindings = json.loads(verify_ref(corpus["embedding_bindings"]))
    binding_map = {(row["id"], row["role"]): row for row in bindings}
    if len(binding_map) != len(bindings):
        raise ValueError("duplicate embedding binding")
    seen, expected_bindings = set(), set()
    for split, rows in corpus["splits"].items():
        if len(rows) != plan["split_counts"].get(split):
            raise ValueError("split count differs from frozen plan")
        for row in rows:
            row_id = row["id"]
            if row_id in seen or row_id not in planned:
                raise ValueError("duplicate or unplanned row")
            seen.add(row_id)
            expected = planned[row_id]
            if expected["split"] != split or sha(row["source_text"].encode()) != expected["source_sha256"] or row["source_sha256"] != expected["source_sha256"]:
                raise ValueError("source differs from frozen plan")
            for key in ("family_group", "template_id", "qualifier_pattern", "canonical_target_sha256"):
                if row.get(key) != expected.get(key):
                    raise ValueError("partition metadata differs from frozen plan")
            if split in {"challenge", "oov"} and {"canonical_ir", "source_spans", "formal_embedding", "formal_embedding_status"} & set(row):
                raise ValueError("sealed or unreviewed input contains target access")
            if split in {"train", "tuning"}:
                if sha(canonical_bytes(row["canonical_ir"])) != expected["canonical_target_sha256"]:
                    raise ValueError("visible target differs from frozen plan")
                if source_spans(row["source_text"], row["canonical_ir"]) != row["source_spans"]:
                    raise ValueError("visible span annotation differs")
            if split != "train" and any(key.startswith("formal_embedding") for key in row):
                raise ValueError("formal embeddings are train only")
            for role in (["source", "formal"] if split == "train" else ["source"]):
                expected_bindings.add((row_id, role))
                binding = binding_map[(row_id, role)]
                text = row["source_text"] if role == "source" else formal_text(row["canonical_ir"])
                if binding["split"] != split or binding["text_sha256"] != sha(text.encode()) or receipt_roles[binding["receipt_sha256"]] != role:
                    raise ValueError("embedding binding differs")
                result = native[(binding["receipt_sha256"], binding["input_id"])]
                item = native_inputs[(binding["receipt_sha256"], binding["input_id"])]
                if item["text"] != text or item["source"]["artifact"]["sha256"] != binding["text_sha256"]:
                    raise ValueError("native vector bound to different input text")
                vector = list(struct.unpack(">384f", bytes.fromhex(result["vector"]["bits"]))) if result["status"] == "embedded" else None
                key = "embedding" if role == "source" else "formal_embedding"
                if row[key] != vector or row[key + "_status"] != result["status"]:
                    raise ValueError("embedding vector differs from native receipt")
                if split != "oov" and vector is None:
                    raise ValueError("authored source lacks native vector")
    if seen != set(planned) or expected_bindings != set(binding_map):
        raise ValueError("missing rows or unexpected target bindings")
    return {"schema": "legal-span-input-validation/v1", "source_rows": len(seen),
            "formal_rows": len(corpus["splits"]["train"]), "native_receipts": len(corpus["embedding_receipts"]),
            "sealed_target_json_parsed": False, "native_vectors_verified": True,
            "visible_source_spans_verified": True, "formal_targets_train_only": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--review-queue", type=Path, default=QUEUE)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.output_directory, review_queue=args.review_queue), sort_keys=True))


if __name__ == "__main__":
    main()
