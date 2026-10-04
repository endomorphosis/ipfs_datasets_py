#!/usr/bin/env python3
"""Freeze exact earlier/new training pools and a separate fresh authored panel.

Earlier rows keep their recorded facet coordinates and have no trigger labels.
Training readers do not open challenge targets or the exposure-audit artifact.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_grounding_curriculum as prior

SCHEMA = "legal-mixed-replay-corpus/v1"
ROW_KEYS = prior.ROW_KEYS | {"domain", "trigger_supervised"}
FIELDS = prior.FIELDS
EXPECTED = {"train_earlier": 1152, "train_new": 600, "tuning_earlier": 96, "tuning_new": 96, "challenge": 144}
DEFAULT_EARLIER = prior.DEFAULT_HISTORICAL
DEFAULT_NEW = prior.ARTIFACTS / "legal-decoder-grounding-20261002/corpus-01/manifest.json"
NAMES = ("Amberwick", "Brackenhall", "Cresswell", "Dovemere", "Everden", "Fleetcombe", "Goldwick", "Heatherby")
CONSTRUCTIONS = ("suffix_rule", "citation_condition_rule", "actor_condition_rule", "temporal_condition_rule",
                 "exception_actor_condition_rule", "citation_semicolon_rule")
LAYOUTS = {
    "suffix_rule": "A M V X [if C] [unless E] [T].",
    "citation_condition_rule": "Under citation, if C, A M V X [unless E] [T].",
    "actor_condition_rule": "A, if C, M V X [unless E] [T].",
    "temporal_condition_rule": "T, A M V X [if C] [unless E].",
    "exception_actor_condition_rule": "Unless E, A, if C, M V X [T].",
    "citation_semicolon_rule": "Under citation, A M V X; this rule applies if C [unless E] [T].",
}
canonical_bytes, sha, file_ref = prior.canonical_bytes, prior.sha, prior.file_ref
read_ref, verify_ref, write_new = prior.read_ref, prior.verify_ref, prior.write_new


def validate_row(row):
    if set(row) != ROW_KEYS or row["domain"] not in {"earlier", "new"} or type(row["trigger_supervised"]) is not bool:
        raise ValueError("closed mixed-supervision row required")
    if row["domain"] == "new":
        if not row["trigger_supervised"]:
            raise ValueError("new rows require explicit trigger supervision")
        prior.validate_row({k: row[k] for k in prior.ROW_KEYS})
        return row
    if row["trigger_span"] is not None or row["trigger_supervised"]:
        raise ValueError("earlier rows must not acquire guessed trigger labels")
    if not isinstance(row["id"], str) or not row["id"]:
        raise ValueError("nonempty identity required")
    text, ir = row["source_text"], row["canonical_ir"]
    if not isinstance(text, str) or not text or set(ir) != {"rules"} or len(ir["rules"]) != 1:
        raise ValueError("nonempty source and one rule required")
    rule = ir["rules"][0]
    if set(rule) != {"modality", *FIELDS} or rule["modality"] not in {"O", "P", "F"} or set(row["facet_spans"]) != set(FIELDS):
        raise ValueError("closed deontic rule and coordinate map required")
    tokens = list(re.finditer(r"\w+|[^\w\s]", text))
    starts, ends, occupied = {t.start() for t in tokens}, {t.end() for t in tokens}, []
    for field, span in row["facet_spans"].items():
        value = rule[field]
        if field in FIELDS[3:]:
            if not isinstance(value, list) or len(value) > 1:
                raise ValueError("at most one qualifier atom required")
            atom = value[0] if value else None
        else:
            if not isinstance(value, str) or not value and field != "object":
                raise ValueError("nonempty actor/action strings required")
            atom = value or None
        if atom is None:
            if span is not None:
                raise ValueError("absent facet has a span")
            continue
        if (not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span)
                or not 0 <= span[0] < span[1] <= len(text) or span[0] not in starts or span[1] not in ends
                or text[slice(*span)] != atom):
            raise ValueError("facet must equal its token-aligned source slice")
        if any(span[0] < b and a < span[1] for a, b in occupied):
            raise ValueError("facet coordinates overlap")
        occupied.append(span)
    return row


def convert_earlier(row):
    text = row["source_text"]
    if row.get("source_sha256", sha(text.encode())) != sha(text.encode()):
        raise ValueError("earlier source hash differs")
    if row.get("canonical_target_sha256", sha(canonical_bytes(row["canonical_ir"]))) != sha(canonical_bytes(row["canonical_ir"])):
        raise ValueError("earlier target hash differs")
    facets = {}
    for field in FIELDS:
        value = row["source_spans"][field]
        if field in FIELDS[3:]:
            if not isinstance(value, list) or len(value) > 1:
                raise ValueError("unsupported earlier qualifier cardinality")
            facets[field] = value[0] if value else None
        else:
            facets[field] = value or None
    return validate_row({"id": row["id"], "source_text": text, "canonical_ir": row["canonical_ir"],
        "facet_spans": facets, "trigger_span": None, "trigger_supervised": False, "domain": "earlier"})


def convert_new(row):
    prior.validate_row(row)
    return validate_row({**row, "domain": "new", "trigger_supervised": True})


def render_challenge(construction, index, modality):
    if construction not in CONSTRUCTIONS or not 0 <= index < len(NAMES) or modality not in {"O", "P", "F"}:
        raise ValueError("unknown challenge construction/index/modality")
    name = NAMES[index]
    actor = prior.ACTOR_FORMS[index].format(name=name)
    values = {"actor": actor, "action": ("inspect", "retain", "submit", "archive", "review", "publish", "inspect", "retain")[index],
        "object": f"the {name.lower()} register number {701 + index}",
        "conditions": (f"{actor} receives the permit" if index % 3 == 0 else f"the {name.lower()} permit is active"),
        "exceptions": (f"{actor} receives an exemption" if index % 4 == 0 else f"the {name.lower()} exemption is active"),
        "temporal": f"within {47 + index} days"}
    present = {field for bit, field in enumerate(FIELDS[3:]) if index & 1 << bit}
    present.update({"citation_condition_rule": {"conditions"}, "actor_condition_rule": {"conditions"},
        "temporal_condition_rule": {"temporal"}, "exception_actor_condition_rule": {"conditions", "exceptions"},
        "citation_semicolon_rule": {"conditions"}}.get(construction, set()))
    remaining, writer = set(present), prior.CoordinateWriter()

    def facet(field):
        writer.add(values[field], field)
        remaining.discard(field)

    def qualifier(field, before, after):
        writer.add(before)
        facet(field)
        writer.add(after)

    if construction in {"citation_condition_rule", "citation_semicolon_rule"}:
        writer.add(f"Under section {1701 + index}(d), ")
    if construction == "citation_condition_rule":
        qualifier("conditions", "if ", ", ")
    elif construction == "temporal_condition_rule":
        qualifier("temporal", "", ", ")
    elif construction == "exception_actor_condition_rule":
        qualifier("exceptions", "Unless ", ", ")
    facet("actor")
    if construction in {"actor_condition_rule", "exception_actor_condition_rule"}:
        qualifier("conditions", ", if ", ", ")
    else:
        writer.add(" ")
    modal_set = prior.MODALS[(index + CONSTRUCTIONS.index(construction)) % len(prior.MODALS)]
    writer.add(modal_set[modality], "trigger")
    writer.add(" ")
    facet("action")
    writer.add(" ")
    facet("object")
    if construction == "citation_semicolon_rule":
        qualifier("conditions", "; this rule applies if ", "")
    for field in FIELDS[3:]:
        if field in remaining:
            qualifier(field, {"conditions": " if ", "exceptions": " unless ", "temporal": " "}[field], "")
    writer.add(".")
    rule = {"modality": modality, **{f: values[f] for f in FIELDS[:3]},
        **{f: [values[f]] if f in present else [] for f in FIELDS[3:]}}
    return validate_row({"id": "mixed-challenge-" + sha(writer.text.encode())[:20], "source_text": writer.text,
        "canonical_ir": {"rules": [rule]}, "trigger_span": writer.spans["trigger"],
        "facet_spans": {f: writer.spans.get(f) for f in FIELDS}, "domain": "new", "trigger_supervised": True})


def make_challenge():
    rows, membership = [], {}
    for construction in CONSTRUCTIONS:
        for index in range(8):
            for modality in ("O", "P", "F"):
                row = render_challenge(construction, index, modality)
                rows.append(row)
                membership[row["id"]] = construction
    return sorted(rows, key=lambda r: sha(r["source_text"].encode())), membership


def skeleton(row):
    """Exact role-masked layout for exposure auditing, not an inference parser.

    Only given facet coordinates are masked. Modal text stays literal for both
    domains, so missing earlier trigger annotations are never reconstructed.
    Unmasked numbers/citation letters are normalized to avoid false novelty.
    """
    text = row["source_text"]
    spans = sorted((v[0], v[1], field) for field, v in row["facet_spans"].items() if v is not None)
    pieces, cursor = [], 0
    for left, right, field in spans:
        pieces.extend((text[cursor:left], "<" + field + ">"))
        cursor = right
    pieces.append(text[cursor:])
    masked = "".join(pieces).casefold()
    masked = re.sub(r"\b\d+\b", "#", masked)
    masked = re.sub(r"(?<=\()\w(?=\))", "#", masked)
    return " ".join(masked.split())


def verify_pools(train, earlier_tune, new_tune, challenge_sources):
    if Counter(r["domain"] for r in train) != {"earlier": EXPECTED["train_earlier"], "new": EXPECTED["train_new"]}:
        raise ValueError("training domain counts differ from exact frozen pools")
    if len(earlier_tune) != EXPECTED["tuning_earlier"] or len(new_tune) != EXPECTED["tuning_new"] or len(challenge_sources) != EXPECTED["challenge"]:
        raise ValueError("tuning/challenge count differs")
    ids, sources = set(), set()
    for label, rows in (("train", train), ("earlier", earlier_tune), ("new", new_tune), ("source", challenge_sources)):
        for row in rows:
            if label == "source":
                if set(row) != {"id", "source_text"}:
                    raise ValueError("challenge inference panel must contain sources only")
            else:
                validate_row(row)
                if label in {"earlier", "new"} and row["domain"] != label:
                    raise ValueError("tuning domain differs")
            normalized = prior.normalized_source(row["source_text"])
            if row["id"] in ids or normalized in sources:
                raise ValueError("duplicate source or identity across pools")
            ids.add(row["id"])
            sources.add(normalized)


def freeze(output, earlier_path=DEFAULT_EARLIER, new_manifest_path=DEFAULT_NEW):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    earlier_ref, new_ref = file_ref(earlier_path), file_ref(new_manifest_path)
    earlier = read_ref(earlier_ref)
    new_manifest, new_train, new_tune, new_exposed_sources = prior.load_training_inputs(new_manifest_path)
    earlier_train = [convert_earlier(r) for r in earlier["splits"]["train"]]
    earlier_tune = [convert_earlier(r) for r in earlier["splits"]["tuning"]]
    new_train, new_tune = [convert_new(r) for r in new_train], [convert_new(r) for r in new_tune]
    train = earlier_train + new_train
    challenge, membership = make_challenge()
    challenge_sources = [{"id": r["id"], "source_text": r["source_text"]} for r in challenge]
    verify_pools(train, earlier_tune, new_tune, challenge_sources)
    exclusions = set(prior.extract_sources(earlier)) | {r["source_text"] for r in new_train + new_tune + new_exposed_sources}
    excluded_exact = {sha(text.encode()) for text in exclusions}
    excluded_normalized = {prior.normalized_source(text) for text in exclusions}
    if any(sha(r["source_text"].encode()) in excluded_exact or prior.normalized_source(r["source_text"]) in excluded_normalized for r in challenge):
        raise ValueError("fresh challenge overlaps an earlier/new source")
    # Only the data-preparation process opens previously exposed new targets to
    # audit surface exposure. No exposed row is appended to training or tuning.
    exposed_targets = [convert_new(r) for r in read_ref(new_manifest["artifacts"]["challenge_targets"])]
    compare_pools = {"earlier_train": earlier_train, "new_train": new_train,
        "earlier_tuning": earlier_tune, "new_tuning": new_tune, "exposed_grounding_challenge": exposed_targets}
    skeletons = {name: {skeleton(r) for r in rows} for name, rows in compare_pools.items()}
    exposure_rows = []
    for row in challenge:
        form = skeleton(row)
        exposure_rows.append({"id": row["id"], "construction": membership[row["id"]], "role_masked_surface": form,
            "matching_pools": [name for name, forms in skeletons.items() if form in forms],
            "previously_unmatched_surface_is_not_a_proof_of_inherited_novelty": True})
    exposure = {"schema": "legal-mixed-surface-exposure-audit/v1", "rows": exposure_rows,
        "method": "Exact source layout after replacing only recorded facet slices, lowercasing and normalizing unmasked digits/citation letters. Modal text remains literal, so no missing trigger label is guessed.",
        "matching_pool_counts": {name: sum(name in r["matching_pools"] for r in exposure_rows) for name in compare_pools},
        "unmatched_in_compared_pools": sum(not r["matching_pools"] for r in exposure_rows),
        "known_earlier_template_ids": sorted({str(r.get("template_id")) for r in earlier["splits"]["train"]}),
        "scope": "Compares admitted earlier/new training, separate tuning pools and exposed grounding challenge. Does not exhaustively reconstruct inherited checkpoints' earlier curricula, pretraining, equivalent paraphrases or whole construction families.",
        "claims_inherited_construction_novelty": False, "new_source_disjointness_verified": True}
    artifacts = {"train": write_new(output / "train.json", train),
        "tuning_earlier": write_new(output / "tuning-earlier.json", earlier_tune),
        "tuning_new": write_new(output / "tuning-new.json", new_tune),
        "challenge_sources": write_new(output / "challenge-sources.json", challenge_sources),
        "challenge_targets": write_new(output / "challenge-targets.sealed.json", challenge),
        "exposure_audit": write_new(output / "surface-exposure-audit.sealed.json", exposure)}
    inventory = {"train": train, "tuning_earlier": earlier_tune, "tuning_new": new_tune, "challenge": challenge}
    manifest = {"schema": SCHEMA, "artifacts": artifacts, "generator": file_ref(__file__),
        "dependencies": {"coordinate_helpers": file_ref(prior.__file__)}, "inputs": {"earlier_corpus": earlier_ref, "new_curriculum": new_ref},
        "frozen_before_fitting": True, "training_performed": False, "qualified": False,
        "provenance": "authored_synthetic_not_legal_authority", "independently_reviewed": False,
        "counts": {**EXPECTED, "train": len(train), "tuning_total": len(earlier_tune) + len(new_tune)},
        "row_schema": {"exact_keys": sorted(ROW_KEYS), "earlier": "trigger_span=null, trigger_supervised=false; facet coordinates copied from existing source_spans", "new": "explicit trigger_span, trigger_supervised=true", "coordinate_unit": "half-open Python string character offsets"},
        "source_membership": {name: [{"id": r["id"], "sha256": sha(r["source_text"].encode())} for r in rows] for name, rows in inventory.items()},
        "training_pool_identity": {"earlier_ordered_rows_sha256": sha(canonical_bytes(earlier_train)), "new_ordered_rows_sha256": sha(canonical_bytes(new_train)),
            "earlier_ids_match_input_training_exactly": [r["id"] for r in earlier_train] == [r["id"] for r in earlier["splits"]["train"]],
            "new_ids_match_input_training_exactly": [r["id"] for r in new_train] == [r["id"] for r in read_ref(new_manifest["artifacts"]["train"])]},
        "challenge": {"construction_layouts": LAYOUTS, "modalities": dict(Counter(r["canonical_ir"]["rules"][0]["modality"] for r in challenge)),
            "source_exclusion_unique_texts": len(exclusions), "source_exact_overlaps": 0, "source_normalized_overlaps": 0,
            "construction_ids_do_not_establish_novelty": True, "claims_inherited_construction_novelty": False},
        "semantics": new_manifest["semantics"], "exposure_summary": {k: exposure[k] for k in ("matching_pool_counts", "unmatched_in_compared_pools", "claims_inherited_construction_novelty")},
        "limits": ["Challenge sources are newly authored and distinct; rendering families may already have been exposed.", "No observed challenge row was promoted into training.", "Earlier trigger annotations remain unavailable, not negative labels.", "Sealed targets are separate files, not encrypted access control.", "No independent statutory gold or full logic-family correctness claim."]}
    return write_new(output / "manifest.json", manifest)


def load_training_inputs(manifest_path):
    """Return manifest, train, earlier tune, new tune, source-only challenge.

    Never opens challenge_targets or exposure_audit, even to verify their hashes.
    The runner may flatten tuning as earlier_tune + new_tune for checkpoint pins.
    """
    manifest = json.loads(Path(manifest_path).read_bytes())
    if manifest.get("schema") != SCHEMA or manifest.get("frozen_before_fitting") is not True:
        raise ValueError("frozen mixed replay manifest required")
    verify_ref(manifest["generator"])
    verify_ref(manifest["dependencies"]["coordinate_helpers"])
    train, earlier_tune, new_tune, challenge = (read_ref(manifest["artifacts"][k]) for k in
        ("train", "tuning_earlier", "tuning_new", "challenge_sources"))
    verify_pools(train, earlier_tune, new_tune, challenge)
    for name, rows in (("train", train), ("tuning_earlier", earlier_tune), ("tuning_new", new_tune), ("challenge", challenge)):
        if [{"id": r["id"], "sha256": sha(r["source_text"].encode())} for r in rows] != manifest["source_membership"][name]:
            raise ValueError("frozen source membership differs")
    for domain in ("earlier", "new"):
        if sha(canonical_bytes([r for r in train if r["domain"] == domain])) != manifest["training_pool_identity"][domain + "_ordered_rows_sha256"]:
            raise ValueError("ordered training pool differs")
    return manifest, train, earlier_tune, new_tune, challenge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--earlier-corpus", type=Path, default=DEFAULT_EARLIER)
    parser.add_argument("--new-manifest", type=Path, default=DEFAULT_NEW)
    args = parser.parse_args()
    print(json.dumps(freeze(args.output, args.earlier_corpus, args.new_manifest), sort_keys=True))


if __name__ == "__main__":
    main()
