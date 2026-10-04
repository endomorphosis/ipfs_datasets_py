#!/usr/bin/env python3
"""Author and freeze role-anchoring clauses; never label statutes or cache outputs.

These controlled examples declare a single norm, conjunction of activation
conditions, and any-exception waiver.  Explicitly marked editorial headings and
cross-reference notes are nonoperative by author stipulation.  They do not teach
that real statutory headings or unresolved references can be discarded.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_clause_consistency_corpus as previous
from scripts.ops.legal_ir import run_legal_clause_consistency_experiment as experiment

mixed, prior = previous.mixed, previous.prior
require, sha, file_ref, read_ref, verify_ref, write_new = (
    getattr(previous, name) for name in ("require", "sha", "file_ref", "read_ref", "verify_ref", "write_new"))
SCHEMA = "authored-legal-role-curriculum/v1"
FIELDS = previous.FIELDS
FAMILIES = ("numbered_heading", "preposed_date", "editorial_cross_reference", "extent_framing")
COUNTS = {"train": 384, "tuning": 96, "fresh": 144}
PER_MODAL_FAMILY = {"train": 16, "tuning": 4, "fresh": 6}
PREFIXES = {"train": "Ashgrove", "tuning": "Birchwater", "fresh": "Elmharbor"}
VERBS = {
    "train": ("retain", "inspect", "archive", "issue", "transfer", "record", "process", "submit"),
    "tuning": ("classify", "authenticate", "publish", "register"),
    "fresh": ("reconcile", "catalogue", "deliver", "review", "certify", "preserve"),
}
ROLE_NOUNS = {"train": ("registrar", "licensing office", "records board", "archive custodian"),
    "tuning": ("commissioner", "inspection unit", "permit office", "review authority"),
    "fresh": ("administrator", "filing bureau", "public register", "custody officer")}
SEALED = ("challenge_targets", "challenge_pairs", "annotation_ledger", "exposure_audit")
DEFAULT_PRIOR = Path("/home/barberb/lift_coding/artifacts/legal-decoder-clause-consistency-20261003/corpus-01/manifest.json")


def validate_row(row):
    """Validate authored coordinates, including explicitly stipulated `may not`."""
    require(type(row) is dict and set(row) == set(mixed.ROW_KEYS) and row["domain"] == "new"
            and row["trigger_supervised"] is True, "closed authored coordinate row required")
    text = row["source_text"]
    require(type(text) is str and bool(text) and type(row["id"]) is str and bool(row["id"]), "authored source/id required")
    require(re.fullmatch(r"role-(?:train|tuning|fresh)-" + sha(text.encode())[:24], row["id"]) is not None,
            "authored identity must commit its exact source text")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as runtime
    rule = runtime.span.codec_module._rule(row["canonical_ir"])
    tokens = runtime.span.tokenize_source(text)
    require(set(row["facet_spans"]) == set(FIELDS), "complete authored facet map required")
    trigger = runtime._span_indices(row["trigger_span"], tokens, text, "trigger")
    cue = text[slice(*row["trigger_span"])]
    require({"shall": "O", "must": "O", "may": "P", "is permitted to": "P", "may not": "F", "must not": "F"}.get(cue)
            == rule["modality"], "trigger differs from explicitly authored force")
    occupied = set(range(trigger[0], trigger[1] + 1))
    for name in FIELDS:
        value = rule[name]
        if name in FIELDS[3:]:
            require(type(value) is list and len(value) <= 1, "one authored qualifier atom per facet")
            value = value[0] if value else ""
        span = row["facet_spans"][name]
        if not value:
            require(name in FIELDS[3:] and span is None, "absent authored qualifier needs null span")
            continue
        indices = runtime._span_indices(span, tokens, text, name)
        positions = set(range(indices[0], indices[1] + 1))
        require(text[slice(*span)] == value and not positions & occupied, "authored role/trigger coordinates differ or overlap")
        occupied |= positions
    return row


def _values(panel, family, modality_index, local):
    require(panel in COUNTS and family in FAMILIES, "known authored split and construction required")
    ordinal = (FAMILIES.index(family) * 3 + modality_index) * PER_MODAL_FAMILY[panel] + local
    name = PREFIXES[panel] + f"{ordinal:03d}"
    mask = (local % 8 if panel == "train" else (0, 3, 4, 7)[local] if panel == "tuning"
            else (0, 1, 2, 4, 5, 7)[local])
    if family == "preposed_date":
        mask |= 4
    if family == "extent_framing":
        mask |= 1
    present = {field for bit, field in enumerate(FIELDS[3:]) if mask & (1 << bit)}
    year = {"train": 2031, "tuning": 2033, "fresh": 2037}[panel]
    extent = {"train": "to the maximum extent practicable", "tuning": "to the extent reasonably practicable",
              "fresh": "to the extent feasible"}[panel]
    return {"ordinal": ordinal, "modality": ("O", "P", "F")[modality_index],
        "actor": f"the {name} {ROLE_NOUNS[panel][local % 4]}",
        "action": VERBS[panel][local % len(VERBS[panel])], "object": f"the {name.lower()} filing packet",
        "conditions": extent if family == "extent_framing" else f"the {name.lower()} permit is active",
        "exceptions": f"the {name.lower()} exemption is active",
        "temporal": (f"before {year}-02-{1 + ordinal % 28:02d}" if family == "preposed_date"
                     else f"within {11 + ordinal % 47} days"),
        "present": present, "citation": str(21000 + ordinal), "mask": mask}


def render(panel, family, modality_index, local, side):
    """Author offsets at insertion time, independently for both paired surfaces."""
    require(type(side) is int and side in (0, 1), "two authored pair sides required")
    value = _values(panel, family, modality_index, local)
    writer, placed, editorial = prior.CoordinateWriter(), set(), []
    cue = {"O": ("shall", "must"), "P": ("may", "is permitted to"),
           "F": ("may not", "must not")}[value["modality"]][side]
    def add(text): writer.add(text)
    def field(name): writer.add(value[name], name)
    def q(name, prefix="", suffix=""):
        add(prefix); field(name); add(suffix); placed.add(name)
    def note(text):
        start = len(writer.text); add(text)
        editorial.append({"start_char": start, "end_char": len(writer.text), "source_text": text,
                          "author_stipulated_role": "nonoperative_editorial_context"})
    templates = {
        "train": ("(a) Filing duty.— ", "Record duty [1]. "),
        "tuning": ("I. Administrative duty: ", "Record preservation (iv): "),
        "fresh": ("(ii)(A) Custody.— ", "Subdivision B—Custody: "),
    }
    if family == "numbered_heading":
        note(templates[panel][side])
    if family == "editorial_cross_reference":
        notes = {"train": ("Editorial cross-reference: section {n}. ", "Editorial index [section {n}]: "),
            "tuning": ("Related provision (editorial): section {n}. ", "Reference index—section {n}. "),
            "fresh": ("Reference table entry: section {n}. ", "(See editorial index, section {n}.) ")}
        note(notes[panel][side].format(n=value["citation"]))
    front = family == "preposed_date" and (panel, side) in (("train", 0), ("tuning", 1), ("fresh", 0))
    if front:
        if panel == "tuning": q("temporal", "[", "] ")
        elif panel == "fresh": q("temporal", "Timing (", "). ")
        else: q("temporal", "", ", ")
    if family == "extent_framing" and (panel, side) in (("train", 0), ("tuning", 1), ("fresh", 0)):
        q("conditions", "Rule applies " if panel == "fresh" else "", ": " if panel == "fresh" else "— " if panel == "tuning" else ", ")
    field("actor")
    if family in ("preposed_date", "extent_framing") and panel == "train" and side == 1:
        q("temporal" if family == "preposed_date" else "conditions", ", ", ",")
    add(" "); writer.add(cue, "trigger")
    if family in ("preposed_date", "extent_framing") and panel == "tuning" and side == 0:
        q("temporal" if family == "preposed_date" else "conditions", ", ", ",")
    add(" "); field("action"); add(" "); field("object")
    if "temporal" in value["present"] and "temporal" not in placed:
        q("temporal", ", " if family == "preposed_date" else " ")
    if "conditions" in value["present"] and "conditions" not in placed:
        q("conditions", " " if family == "extent_framing" else {"train": " if ", "tuning": " when ", "fresh": " provided that "}[panel])
    if "exceptions" in value["present"]:
        q("exceptions", {"train": " unless ", "tuning": " except when ", "fresh": " except where "}[panel])
    add(".")
    rule = {"modality": value["modality"], **{name: value[name] for name in FIELDS[:3]},
            **{name: [value[name]] if name in value["present"] else [] for name in FIELDS[3:]}}
    row = validate_row({"id": f"role-{panel}-" + sha(writer.text.encode())[:24], "source_text": writer.text,
        "canonical_ir": {"rules": [rule]}, "trigger_span": writer.spans["trigger"],
        "facet_spans": {name: writer.spans.get(name) for name in FIELDS}, "domain": "new", "trigger_supervised": True})
    # Mask annotated contents, preserving concrete layout/cues/editorial framing.
    intervals = sorted((start, end, name) for name, (start, end) in writer.spans.items())
    template, cursor = "", 0
    for start, end, name in intervals:
        template += writer.text[cursor:start] + "{" + name + "}"
        cursor = end
    template += writer.text[cursor:]
    # Citation numbers are not a basis for declaring a held-out template novel.
    template = re.sub(r"\b[0-9]+\b", "{number}", template)
    annotation = {"id": row["id"], "source_sha256": sha(writer.text.encode()), "panel": panel,
        "family": family, "case_group": f"role-{panel}-{value['ordinal']:03d}",
        "meaning_group": f"role-{panel}-{value['ordinal']:03d}",
        "template_id": f"role-{panel}-{family}-{side}", "template_fingerprint": sha(template.encode()),
        "template": template, "side": side, "presence_mask": value["mask"], "editorial_context": editorial,
        "facet_spans": row["facet_spans"], "trigger_span": row["trigger_span"],
        "annotation_authority": "authored_controlled_example_not_statutory_gold",
        "scope": {"conditions": "all_activate_at_evaluation_origin", "exceptions": "any_waives_at_evaluation_origin",
                  "temporal": "explicit_authored_closed_duration_or_before_calendar_date", "rule_count": 1}}
    return row, annotation


def make_panel(panel):
    rows, annotations, pairs = [], [], []
    for family in FAMILIES:
        for modality in range(3):
            for local in range(PER_MODAL_FAMILY[panel]):
                pair = [render(panel, family, modality, local, side) for side in (0, 1)]
                rows.extend(item[0] for item in pair); annotations.extend(item[1] for item in pair)
                left, right = (item[0] for item in pair)
                require(left["canonical_ir"] == right["canonical_ir"], "authored pair meanings differ")
                pairs.append({"pair_id": pair[0][1]["meaning_group"], "case_group": pair[0][1]["case_group"],
                    "left_id": left["id"], "right_id": right["id"], "canonical_ir_sha256": experiment.digest(left["canonical_ir"])})
    validate_pairs(rows, pairs, COUNTS[panel] // 2)
    return rows, annotations, pairs


def validate_pairs(rows, pairs, expected_pairs):
    require(type(rows) is list and type(pairs) is list and all(type(p) is dict for p in pairs),
            "authored row and pair inventories must be lists of closed records")
    previous.validate_pairs(rows, pairs, expected_pairs)
    require(all(type(p["case_group"]) is str and p["case_group"] == p["pair_id"] for p in pairs)
            and len({p["case_group"] for p in pairs}) == len(pairs),
            "one semantic pair per distinct authored case group required")


def validate_panels(panels, annotations):
    require({name: len(rows) for name, rows in panels.items()} == COUNTS, "authored panel counts differ")
    seen_ids, seen_text, seen_meanings, seen_templates = set(), set(), set(), set()
    for panel in COUNTS:
        rows, labels = panels[panel], annotations[panel]
        ids, texts = {r["id"] for r in rows}, {prior.normalized_source(r["source_text"]) for r in rows}
        meanings = {experiment.digest(r["canonical_ir"]) for r in rows}
        templates = {r["template_fingerprint"] for r in labels}
        require(len(ids) == len(texts) == len(rows) and len(meanings) == len(rows) // 2,
                "distinct authored cases and exactly two surfaces per meaning required")
        require(not (ids & seen_ids or texts & seen_text or meanings & seen_meanings or templates & seen_templates),
                "authored train/tuning/challenge identity, source, meaning or concrete-template overlap")
        require(len(labels) == len(rows) and {r["id"] for r in labels} == ids,
                "complete annotation lineage required")
        by_id = {r["id"]: r for r in rows}
        for label in labels:
            row = by_id[label["id"]]
            require(label["panel"] == panel and label["source_sha256"] == sha(row["source_text"].encode())
                    and label["facet_spans"] == row["facet_spans"] and label["trigger_span"] == row["trigger_span"],
                    "annotation source/coordinate binding differs")
        require(dict(Counter(r["canonical_ir"]["rules"][0]["modality"] for r in rows)) == {m: len(rows) // 3 for m in ("O", "P", "F")},
                "balanced authored O/P/F inventory required")
        seen_ids |= ids; seen_text |= texts; seen_meanings |= meanings; seen_templates |= templates
    return {"source_count": len(seen_text), "meaning_count": len(seen_meanings),
            "cross_split_source_overlap": 0, "cross_split_meaning_overlap": 0, "cross_split_template_overlap": 0,
            "scope": "distinct concrete templates within the new train/tuning/challenge splits and shared construction families; prior-template novelty and unseen grammar are not certified",
            "lexical_scope": "selected split-specific name prefixes, action verbs and role nouns; shared function words, qualifier wording, modal cues, object suffixes and some numeric durations remain exposed"}


def freeze(output, prior_manifest_path, prior_config_path, real_manifest_path):
    prior_inputs = previous.load_training_inputs(prior_manifest_path)
    prior_config = experiment.read(prior_config_path)
    from scripts.ops.legal_ir import evaluate_legal_uscode_fidelity as real
    real_manifest = experiment.read(real_manifest_path)
    real_sources = real.validate_manifest(real_manifest)
    panels, annotations, pairs = {}, {}, {}
    for panel in COUNTS:
        panels[panel], annotations[panel], pairs[panel] = make_panel(panel)
    split_audit = validate_panels(panels, annotations)
    known = [*prior_inputs["new_train"], *prior_inputs["new_tuning"], *prior_inputs["fresh_sources"],
             *prior_inputs["fresh_document_sources"], *real_sources]
    known += [row for pool in prior_inputs["replay"].values() for row in pool]
    known += [row for pool in prior_inputs["tuning"].values() for row in pool]
    source_refs = [value for key, value in prior_config.items() if key.endswith("_sources")]
    for reference in source_refs:
        value = read_ref(reference)
        known.extend(value["challenge"] if type(value) is dict and "challenge" in value else value)
    old_hashes = {sha(prior.normalized_source(row["source_text"]).encode()) for row in known}
    for panel, rows in panels.items():
        require(not {sha(prior.normalized_source(row["source_text"]).encode()) for row in rows} & old_hashes,
                "authored " + panel + " overlaps prior or exposed source text")
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    plan = write_new(output / "plan.json", {"schema": SCHEMA, "counts": COUNTS, "construction_families": list(FAMILIES),
        "splits": "meaning and exact/normalized source groups fixed before fitting; selected content terms and new-split concrete templates differ, while shared qualifier/function vocabulary remains exposed",
        "label_origin": "newly authored controlled examples; no statute or cached compiler labels",
        "cross_reference_policy": "explicit editorial metadata by author stipulation; no unresolved statutory references",
        "fresh_targets_sealed_until_generation_freeze": True})
    artifacts = {
        "new_training": write_new(output / "new-training.json", panels["train"]),
        "training_pairs": write_new(output / "training-pairs.json", pairs["train"]),
        "new_tuning": write_new(output / "new-tuning.json", panels["tuning"]),
        "tuning_pairs": write_new(output / "tuning-pairs.json", pairs["tuning"]),
        "challenge_sources": write_new(output / "challenge-sources.json", [{"id": r["id"], "source_text": r["source_text"]} for r in panels["fresh"]]),
        "challenge_targets": write_new(output / "challenge-targets.sealed.json", panels["fresh"]),
        "challenge_pairs": write_new(output / "challenge-pairs.sealed.json", pairs["fresh"]),
        "annotation_ledger": write_new(output / "annotation-ledger.sealed.json", annotations),
        "exposure_audit": write_new(output / "exposure-audit.sealed.json", {"prior_unique_normalized_sources": len(old_hashes),
            "real_exposed_views": len(real_sources), "prior_inventory_sha256": experiment.digest(sorted(old_hashes)),
            "new_overlap_count": 0, "prior_source_inputs": source_refs, "split_audit": split_audit}),
    }
    manifest = {"schema": SCHEMA, "frozen_before_training": True, "plan": plan,
        "generator": file_ref(__file__), "dependencies": {"previous_corpus": file_ref(previous.__file__),
            "experiment_helpers": file_ref(experiment.__file__), "real_source_validator": file_ref(real.__file__)},
        "inputs": {"prior_corpus": file_ref(prior_manifest_path), "prior_config": file_ref(prior_config_path),
                   "real_source_manifest": file_ref(real_manifest_path)}, "artifacts": artifacts,
        "counts": COUNTS, "split_audit": split_audit, "training_qualified_as_statutory_gold": False,
        "source_semantics_verified": False, "sealed_artifacts": list(SEALED),
        "sealing_scope": "fitting and selection loader never opens challenge targets, pairing labels, annotation ledger or exposure audit"}
    return write_new(output / "manifest.json", manifest)


def load_training_inputs(manifest_path):
    """Admitted supervision plus new source-only challenge; no sealed reads."""
    manifest = json.loads(Path(manifest_path).read_bytes())
    require(manifest.get("schema") == SCHEMA and manifest.get("frozen_before_training") is True, "frozen authored curriculum required")
    require(manifest.get("counts") == COUNTS and manifest.get("sealed_artifacts") == list(SEALED),
            "frozen authored denominators or seal declarations differ")
    verify_ref(manifest["generator"])
    for reference in manifest["dependencies"].values(): verify_ref(reference)
    for reference in manifest["inputs"].values(): verify_ref(reference)
    old = previous.load_training_inputs(manifest["inputs"]["prior_corpus"]["path"])
    artifacts = manifest["artifacts"]
    train, tune = read_ref(artifacts["new_training"]), read_ref(artifacts["new_tuning"])
    pairs, tuning_pairs = read_ref(artifacts["training_pairs"]), read_ref(artifacts["tuning_pairs"])
    validate_pairs(train, pairs, 192); validate_pairs(tune, tuning_pairs, 48)
    for row in train + tune: validate_row(row)
    fresh = read_ref(artifacts["challenge_sources"])
    require(len(fresh) == 144 and all(set(r) == {"id", "source_text"} for r in fresh), "complete source-only fresh inventory required")
    require(all(type(r["source_text"]) is str and bool(r["source_text"])
                and r["id"] == "role-fresh-" + sha(r["source_text"].encode())[:24] for r in fresh),
            "fresh source identity differs")
    fresh_ids = {r["id"] for r in fresh}
    fresh_text = {prior.normalized_source(r["source_text"]) for r in fresh}
    require(len(fresh_ids) == len(fresh_text) == 144
            and not fresh_ids & {r["id"] for r in train + tune}
            and not fresh_text & {prior.normalized_source(r["source_text"]) for r in train + tune},
            "source-only fresh inventory duplicates or overlaps admitted supervision")
    return {"manifest": manifest, "new_train": train, "training_pairs": pairs,
        "new_tuning": tune, "tuning_pairs": tuning_pairs, "fresh_sources": fresh,
        "replay": {**old["replay"], "prior_consistency": old["new_train"]},
        "tuning": {"earlier": old["tuning"]["earlier"], "temporal": old["tuning"]["temporal"],
                   "prior_consistency": old["new_tuning"]}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prior-manifest", default=str(DEFAULT_PRIOR))
    parser.add_argument("--prior-config", required=True)
    parser.add_argument("--real-manifest", required=True)
    args = parser.parse_args()
    print(freeze(args.output, args.prior_manifest, args.prior_config, args.real_manifest))
