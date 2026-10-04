#!/usr/bin/env python3
"""Freeze case-group-disjoint temporal placement and applicability contrasts.

The baseline mixed pools are copied unchanged. Authored temporal conditions are
opaque applicability atoms; their internal calendar arithmetic is not lowered.
Only explicitly annotated action-time limits populate the temporal facet.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_mixed_replay_corpus as mixed

prior = mixed.prior
SCHEMA = "legal-temporal-curriculum/v1"
FIELDS = prior.FIELDS
canonical_bytes, sha, file_ref = prior.canonical_bytes, prior.sha, prior.file_ref
read_ref, verify_ref, write_new = prior.read_ref, prior.verify_ref, prior.write_new
DEFAULT_MIXED = prior.ARTIFACTS / "legal-decoder-mixed-replay-20261002/corpus-01/manifest.json"
DOC_BASE = prior.ARTIFACTS / "legal-decoder-grounding-20261002/clause-boundaries-01/corpus"
DEFAULT_DOCUMENT_SOURCES = tuple(DOC_BASE / (split + "-sources.json") for split in ("train", "tuning", "test"))
VARIANTS = ("deadline_front", "deadline_interleaved", "deadline_end", "deadline_absent", "applicability_front", "applicability_end")
PREFIXES = {
    "train": ("Aster", "Bramble", "Coral", "Drift", "Ember", "Fallow", "Granite", "Harbor", "Indigo", "Linden", "Mallow", "Nacre", "Oriel", "Prairie", "Russet", "Sable", "Tamarisk", "Umber", "Verdant", "Wister"),
    "tuning": ("Acorn", "Beryl", "Clover", "Dapple"),
    "challenge": ("Elder", "Flint", "Garnet", "Hawthorn", "Inkwood", "Jasper"),
}
SUFFIXES = ("port", "brook", "mere", "field", "haven")
COUNTS = {"train": 600, "tuning": 120, "challenge": 180}


def case_values(split, index):
    if split not in PREFIXES or not 0 <= index < len(PREFIXES[split]) * len(SUFFIXES):
        raise ValueError("unknown temporal case")
    name = PREFIXES[split][index // len(SUFFIXES)] + SUFFIXES[index % len(SUFFIXES)]
    offset = {"train": 0, "tuning": 100, "challenge": 200}[split]
    size = len(PREFIXES[split]) * len(SUFFIXES)
    def numeral(slot):
        return random.Random(f"temporal-numerals/v1:{split}:{slot}").sample(range(size), size)[index]
    duration = 17 + offset + numeral("duration")
    actor = prior.ACTOR_FORMS[index % len(prior.ACTOR_FORMS)].format(name=name)
    return {"name": name, "actor": actor,
        "action": ("inspect", "retain", "submit", "archive", "review", "publish")[(index // 3 + index % 3) % 6],
        "object": f"the {name.lower()} register number {3101 + offset + numeral('object')}",
        "conditions": (f"{actor} receives the permit" if index % 7 == 0 else f"the {name.lower()} permit is active"),
        "exceptions": f"the {name.lower()} exemption is active",
        "temporal": f"within {duration} days",
        "applicability": f"the {name.lower()} application is received within {duration} days",
        "citation": f"section {2401 + offset + numeral('citation')}(e)",
        "modality": ("O", "P", "F")[index % 3],
        "trigger": prior.MODALS[(index // 3) % len(prior.MODALS)][("O", "P", "F")[index % 3]],
        "case_group": f"temporal-{split}-{name.lower()}"}


def render(split, index, variant):
    if variant not in VARIANTS:
        raise ValueError("unsupported temporal variant")
    values = case_values(split, index)
    applicability = variant.startswith("applicability_")
    deadline = variant in {"deadline_front", "deadline_interleaved", "deadline_end"}
    has_condition = applicability or index % 2 == 0
    has_exception = (index // 3) % 3 != 0
    condition = values["applicability"] if applicability else values["conditions"]
    present = {"conditions": has_condition, "exceptions": has_exception, "temporal": deadline}
    writer = prior.CoordinateWriter()

    def field(name, value=None):
        writer.add(values[name] if value is None else value, name)

    def qualifier(name, before, after, value=None):
        writer.add(before)
        field(name, value)
        writer.add(after)

    if index % 4 == 1:
        writer.add(f"Under {values['citation']}, ")
    if variant == "deadline_front":
        qualifier("temporal", "", ", ")
    condition_front = variant == "applicability_front" or not applicability and has_condition and index % 4 == 0
    if condition_front:
        qualifier("conditions", "If " if not writer.text else "if ", ", ", condition)
    field("actor")
    if variant == "deadline_interleaved":
        qualifier("temporal", ", ", ", ")
    else:
        writer.add(" ")
    field("trigger", values["trigger"])
    writer.add(" ")
    field("action")
    writer.add(" ")
    field("object")
    if variant == "deadline_end":
        qualifier("temporal", " ", "")
    if has_condition and not condition_front:
        qualifier("conditions", " if ", "", condition)
    if has_exception:
        qualifier("exceptions", " unless ", "")
    writer.add(".")
    rule = {"modality": values["modality"], **{f: values[f] for f in FIELDS[:3]},
        "conditions": [condition] if has_condition else [],
        "exceptions": [values["exceptions"]] if has_exception else [],
        "temporal": [values["temporal"]] if deadline else []}
    row = mixed.validate_row({"id": "temporal-" + split + "-" + sha(writer.text.encode())[:20],
        "source_text": writer.text, "canonical_ir": {"rules": [rule]},
        "facet_spans": {f: writer.spans.get(f) for f in FIELDS}, "trigger_span": writer.spans["trigger"],
        "domain": "new", "trigger_supervised": True})
    placement = {"deadline_front": "before_actor", "deadline_interleaved": "between_actor_and_modal",
        "deadline_end": "after_action_object", "deadline_absent": "none",
        "applicability_front": "condition_before_actor", "applicability_end": "condition_after_object"}[variant]
    ledger = {"id": row["id"], "source_sha256": sha(writer.text.encode()), "split": split,
        "case_group": values["case_group"], "variant": variant, "placement": placement,
        "role": "action_deadline" if deadline else "temporal_applicability_condition" if applicability else "absent",
        "modality": values["modality"], "facet_spans": row["facet_spans"], "trigger_span": row["trigger_span"]}
    return row, ledger


def validate_panels(panels, ledger):
    by_id = {row["id"]: row for row in ledger}
    if len(by_id) != len(ledger):
        raise ValueError("duplicate annotation identity")
    seen_ids, seen_sources, groups = set(), set(), {}
    for split, rows in panels.items():
        if len(rows) != COUNTS[split]:
            raise ValueError("temporal panel count differs")
        grouped = {}
        for row in rows:
            mixed.validate_row(row)
            normalized = prior.normalized_source(row["source_text"])
            if row["id"] in seen_ids or normalized in seen_sources:
                raise ValueError("duplicate temporal source or identity")
            seen_ids.add(row["id"])
            seen_sources.add(normalized)
            annotation = by_id[row["id"]]
            if annotation["split"] != split or annotation["source_sha256"] != sha(row["source_text"].encode()):
                raise ValueError("annotation source/split binding differs")
            if annotation["facet_spans"] != row["facet_spans"] or annotation["trigger_span"] != row["trigger_span"]:
                raise ValueError("annotation coordinate binding differs")
            group = annotation["case_group"]
            if group in groups and groups[group] != split:
                raise ValueError("case group crosses splits")
            groups[group] = split
            grouped.setdefault(group, []).append((row, annotation))
        for records in grouped.values():
            if Counter(a["variant"] for _, a in records) != Counter(VARIANTS):
                raise ValueError("every case must retain all six variants exactly once")
            base = records[0][0]["canonical_ir"]["rules"][0]
            for row, annotation in records:
                rule = row["canonical_ir"]["rules"][0]
                if any(rule[f] != base[f] for f in ("modality", "actor", "action", "object", "exceptions")):
                    raise ValueError("case invariant actor/action/object/modality/exception differs")
                if annotation["modality"] != rule["modality"]:
                    raise ValueError("annotation modality differs")
                if annotation["role"] == "temporal_applicability_condition" and (rule["temporal"] or len(rule["conditions"]) != 1):
                    raise ValueError("applicability condition incorrectly becomes an action deadline")
    if seen_ids != set(by_id):
        raise ValueError("annotation coverage differs")


def make_panels():
    panels, ledger = {}, []
    for split, prefixes in PREFIXES.items():
        rows = []
        for index in range(len(prefixes) * len(SUFFIXES)):
            for variant in VARIANTS:
                row, annotation = render(split, index, variant)
                rows.append(row)
                ledger.append(annotation)
        panels[split] = sorted(rows, key=lambda r: sha(r["source_text"].encode()))
    validate_panels(panels, ledger)
    return panels, ledger


def verify_new_source_disjointness(panels, excluded_sources):
    exact = {sha(text.encode()) for text in excluded_sources}
    normalized = {prior.normalized_source(text) for text in excluded_sources}
    for rows in panels.values():
        for row in rows:
            if sha(row["source_text"].encode()) in exact or prior.normalized_source(row["source_text"]) in normalized:
                raise ValueError("new temporal source overlaps a prior pool")


def freeze(output, mixed_manifest_path=DEFAULT_MIXED, document_sources=DEFAULT_DOCUMENT_SOURCES):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    mixed_ref = file_ref(mixed_manifest_path)
    mixed_manifest, baseline, earlier_tune, newer_tune, exposed_mixed_sources = mixed.load_training_inputs(mixed_manifest_path)
    panels, annotations = make_panels()
    augmented = baseline + panels["train"]
    previous_earlier = read_ref(mixed_manifest["inputs"]["earlier_corpus"])
    previous_new_manifest = read_ref(mixed_manifest["inputs"]["new_curriculum"])
    previous_exposed_grounding_sources = read_ref(previous_new_manifest["artifacts"]["challenge_sources"])
    exclusions = set(prior.extract_sources(previous_earlier)) | {
        r["source_text"] for r in baseline + earlier_tune + newer_tune + exposed_mixed_sources + previous_exposed_grounding_sources}
    document_refs = []
    for path in document_sources:
        reference = file_ref(path)
        data = read_ref(reference)
        sources = set(prior.extract_sources(data))
        if not sources:
            raise ValueError("document source exclusion inventory is empty")
        exclusions.update(sources)
        document_refs.append({"artifact": reference, "unique_sources": len(sources)})
    if not document_refs:
        raise ValueError("document source exclusion inventories are required")
    verify_new_source_disjointness(panels, exclusions)
    # Prior exposed annotations are read only while preparing exposure evidence;
    # their rows never enter either training arm or any new tuning partition.
    old_exposed_ground = [mixed.convert_new(r) for r in read_ref(previous_new_manifest["artifacts"]["challenge_targets"])]
    old_exposed_mixed = read_ref(mixed_manifest["artifacts"]["challenge_targets"])
    comparisons = {"earlier_training": [r for r in baseline if r["domain"] == "earlier"],
        "baseline_new_training": [r for r in baseline if r["domain"] == "new"],
        "earlier_tuning": earlier_tune, "prior_new_tuning": newer_tune,
        "exposed_grounding150": old_exposed_ground, "exposed_mixed144": old_exposed_mixed,
        "temporal_training": panels["train"], "temporal_tuning": panels["tuning"]}
    skeletons = {name: {mixed.skeleton(r) for r in rows} for name, rows in comparisons.items()}
    indexed = {r["id"]: r for r in annotations}
    exposure_rows = [{"id": row["id"], "case_group": indexed[row["id"]]["case_group"],
        "variant": indexed[row["id"]]["variant"], "role_masked_surface": mixed.skeleton(row),
        "matching_pools": [name for name, values in skeletons.items() if mixed.skeleton(row) in values]}
        for row in panels["challenge"]]
    exposure = {"schema": "legal-temporal-surface-exposure/v1", "rows": exposure_rows,
        "matching_pool_counts": {name: sum(name in row["matching_pools"] for row in exposure_rows) for name in comparisons},
        "unmatched_exact_surface_count": sum(not row["matching_pools"] for row in exposure_rows),
        "case_groups_disjoint": True, "claims_inherited_construction_novelty": False,
        "method": "Exact role-masked surface comparison; masks only supplied facet coordinates, retains modal words, normalizes unmasked numbers/citation letters.",
        "scope": "New source and case identities are held out. Template families intentionally recur across temporal splits for controlled generalization; source identity and case separation do not imply unseen rendering families or exhaustive inherited exposure."}
    ledger = {"schema": "legal-temporal-case-annotations/v1", "rows": annotations,
        "all_case_variants_kept_in_one_split": True, "case_group_variants": list(VARIANTS),
        "semantics": "Applicability variants use a complete opaque conditions atom and temporal=[]; action deadline variants populate temporal with an independently bound source span."}
    artifacts = {
        "training_baseline": write_new(output / "training-baseline.json", baseline),
        "training_temporal_augmented": write_new(output / "training-temporal-augmented.json", augmented),
        "temporal_training": write_new(output / "temporal-training.json", panels["train"]),
        "tuning_earlier": write_new(output / "tuning-earlier.json", earlier_tune),
        "tuning_prior_new": write_new(output / "tuning-prior-new.json", newer_tune),
        "tuning_temporal": write_new(output / "tuning-temporal.json", panels["tuning"]),
        "challenge_sources": write_new(output / "challenge-sources.json", [{"id": r["id"], "source_text": r["source_text"]} for r in panels["challenge"]]),
        "challenge_targets": write_new(output / "challenge-targets.sealed.json", panels["challenge"]),
        "annotation_ledger": write_new(output / "case-annotations.sealed.json", ledger),
        "exposure_audit": write_new(output / "surface-exposure.sealed.json", exposure),
    }
    manifest = {"schema": SCHEMA, "artifacts": artifacts, "generator": file_ref(__file__),
        "dependencies": {"mixed_helpers": file_ref(mixed.__file__), "coordinate_helpers": file_ref(prior.__file__)},
        "inputs": {"mixed_corpus": mixed_ref, "document_source_inventories": document_refs},
        "frozen_before_fitting": True, "qualified": False, "independently_reviewed": False,
        "provenance": "authored_synthetic_not_legal_authority", "training_performed": False,
        "counts": {"training_baseline": len(baseline), "training_temporal_augmented": len(augmented),
            "earlier_training": 1152, "baseline_new_training": 600, "temporal_training": 600,
            "augmented_new_training": 1200, "tuning_earlier": 96, "tuning_prior_new": 96,
            "tuning_temporal": 120, "tuning_total": 312, "challenge": 180},
        "baseline_ordered_rows_sha256": sha(canonical_bytes(baseline)),
        "augmented_equals_baseline_plus_declared_temporal_training": True,
        "case_groups": {split: sorted({r["case_group"] for r in annotations if r["split"] == split}) for split in panels},
        "temporal_split_summaries": {split: {"count": len(rows),
            "modalities": dict(Counter(r["canonical_ir"]["rules"][0]["modality"] for r in rows)),
            "variants": dict(Counter(r["variant"] for r in annotations if r["split"] == split)),
            "case_group_count": len({r["case_group"] for r in annotations if r["split"] == split})} for split, rows in panels.items()},
        "slot_modality_audit": {"training_action_modalities": {action: sorted({r["canonical_ir"]["rules"][0]["modality"] for r in panels["train"] if r["canonical_ir"]["rules"][0]["action"] == action})
            for action in sorted({r["canonical_ir"]["rules"][0]["action"] for r in panels["train"]})},
            "training_exception_presence_modalities": {str(present): sorted({r["canonical_ir"]["rules"][0]["modality"] for r in panels["train"] if bool(r["canonical_ir"]["rules"][0]["exceptions"]) is present}) for present in (False, True)},
            "numeric_assignment": "Duration, object and citation numerals use separately seeded permutations per split, not case-index modulo3. Each case retains its assigned values across allsix variants.",
            "scope": "Checks named slot proxies, not proof that all possible linguistic correlations are absent."},
        "source_membership": {name: [{"id": r["id"], "sha256": sha(r["source_text"].encode())} for r in rows]
            for name, rows in {"training_baseline": baseline, "temporal_training": panels["train"],
                "tuning_earlier": earlier_tune, "tuning_prior_new": newer_tune, "tuning_temporal": panels["tuning"],
                "challenge": panels["challenge"]}.items()},
        "source_overlap_audit": {"unique_excluded_texts": len(exclusions), "exact_overlaps": 0, "normalized_overlaps": 0,
            "scope": "All newly authored train/tune/test sources compared with pinned earlier corpus, baseline mixed train/tune, prior150/mixed144 exposed sources and declared document train/tuning/test source inventories."},
        "exposure_summary": {k: exposure[k] for k in ("matching_pool_counts", "unmatched_exact_surface_count", "claims_inherited_construction_novelty")},
        "semantics": {**mixed_manifest["semantics"],
            "action_temporal_qualifier": "within N days qualifies the action under the externally supplied activation anchor; its placement does not change its declared role. O/P/F retain their existing supported deontic/calendar interpretation policy.",
            "action_deadline_role_name": "Ledger role action_deadline means action temporal limit: an obligation deadline for O, a bounded permission for P, and a temporal prohibition scope for F. It does not turn permissions or prohibitions into obligations.",
            "temporal_applicability": "the NAME application is received within N days is copied as one opaque condition atom. Truth and its internal calendar arithmetic are supplied externally, not derived or lowered by this corpus.",
            "absent_deadline": "No action temporal qualifier is asserted. Duration words inside the applicability condition are not an action deadline.",
            "excluded_temporal_scope": ["nested or shared rule scope", "multiple deadlines per rule", "computed relations between two dates", "cross-reference anchor resolution", "temporal condition arithmetic lowering"]},
        "scope": "600 authored temporal training additions;120 separate temporal tuning;180 fresh source- and case-group-disjoint examples. Six rendering variants recur across groups; inherited template novelty and legal authority are not claimed.",
        "limits": ["All six variants preserve actor, action, object, modality and exception within a case.",
            "Applicability variants change the condition role explicitly; they are not claims of semantic equivalence to action deadlines.",
            "No exposed evaluation row is promoted to training.", "Separate target files are not encrypted access control."]}
    return write_new(output / "manifest.json", manifest)


def load_training_inputs(manifest_path):
    """Load fit/tune and source-only challenge without sealed annotation reads."""
    manifest = json.loads(Path(manifest_path).read_bytes())
    if manifest.get("schema") != SCHEMA or manifest.get("frozen_before_fitting") is not True:
        raise ValueError("frozen temporal curriculum manifest required")
    verify_ref(manifest["generator"])
    for reference in manifest["dependencies"].values():
        verify_ref(reference)
    allowed = ("training_baseline", "training_temporal_augmented", "temporal_training", "tuning_earlier", "tuning_prior_new", "tuning_temporal", "challenge_sources")
    loaded = {key: read_ref(manifest["artifacts"][key]) for key in allowed}
    baseline, augmented, added = (loaded[k] for k in allowed[:3])
    if len(baseline) != 1752 or len(augmented) != 2352 or len(added) != 600 or augmented != baseline + added:
        raise ValueError("exact baseline/addition training inventory differs")
    if Counter(r["domain"] for r in baseline) != {"earlier": 1152, "new": 600} or any(r["domain"] != "new" for r in added):
        raise ValueError("training domains differ")
    if sha(canonical_bytes(baseline)) != manifest["baseline_ordered_rows_sha256"]:
        raise ValueError("baseline ordered rows differ")
    ids, normalized = set(), set()
    for name in ("training_baseline", "temporal_training", "tuning_earlier", "tuning_prior_new", "tuning_temporal", "challenge_sources"):
        rows = loaded[name]
        expected_count = manifest["counts"]["challenge" if name == "challenge_sources" else name]
        if len(rows) != expected_count:
            raise ValueError("declared row count differs")
        for row in rows:
            if name == "challenge_sources":
                if set(row) != {"id", "source_text"}:
                    raise ValueError("challenge must contain sources only")
            else:
                mixed.validate_row(row)
                if name.startswith("tuning_") and row["domain"] != ("earlier" if name == "tuning_earlier" else "new"):
                    raise ValueError("tuning partition domain differs")
            key = prior.normalized_source(row["source_text"])
            if row["id"] in ids or key in normalized:
                raise ValueError("fit/tune/challenge source or identity overlaps")
            ids.add(row["id"])
            normalized.add(key)
        member_key = "challenge" if name == "challenge_sources" else name
        if [{"id": r["id"], "sha256": sha(r["source_text"].encode())} for r in rows] != manifest["source_membership"][member_key]:
            raise ValueError("source inventory differs")
    case_sets = [set(manifest["case_groups"][s]) for s in ("train", "tuning", "challenge")]
    if [len(s) for s in case_sets] != [100, 20, 30]:
        raise ValueError("declared case group counts differ")
    if any(a & b for i, a in enumerate(case_sets) for b in case_sets[i + 1:]):
        raise ValueError("declared case groups overlap")
    return {"manifest": manifest, "training": {"baseline": baseline, "temporal_augmented": augmented},
        "tuning": {"earlier": loaded["tuning_earlier"], "prior_new": loaded["tuning_prior_new"], "temporal": loaded["tuning_temporal"]},
        "fresh_sources": loaded["challenge_sources"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mixed-manifest", type=Path, default=DEFAULT_MIXED)
    parser.add_argument("--document-sources", type=Path, action="append")
    args = parser.parse_args()
    print(json.dumps(freeze(args.output, args.mixed_manifest, args.document_sources or DEFAULT_DOCUMENT_SOURCES), sort_keys=True))


if __name__ == "__main__":
    main()
