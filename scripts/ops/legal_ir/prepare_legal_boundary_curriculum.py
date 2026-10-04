#!/usr/bin/env python3
"""Freeze authored boundary training and a sealed construction-combination test.

Only source coordinates authored during rendering supervise boundaries. Historical
labels are read only while preparing exposure evidence, never by fitting loaders.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_construction_retention_corpus as previous

temporal, mixed, prior, documents = previous.temporal, previous.mixed, previous.prior, previous.documents
FIELDS, require = previous.FIELDS, previous.require
sha, file_ref, read_ref, verify_ref, write_new = previous.sha, previous.file_ref, previous.read_ref, previous.verify_ref, previous.write_new
SCHEMA = "legal-boundary-curriculum-corpus/v1"
DEFAULT_PREVIOUS = prior.ARTIFACTS / "legal-decoder-construction-retention-20261002/corpus-01/manifest.json"
COUNTS = {"train": 384, "tuning": 96, "fresh": 96}
SUPPORTED = {"train": 288, "tuning": 72, "fresh": 72}
PREFIXES = {"train": "Silverleaf", "tuning": "Copperleaf", "fresh": "Amberleaf"}
TRAIN_FAMILIES = previous.FAMILIES + previous.TUNING_FAMILIES
FRESH_FAMILIES = ("condition_temporal_front", "exception_temporal_front", "exception_condition_front",
    "temporal_condition_postmodal", "exception_temporal_postmodal", "exception_condition_postmodal")
GUARDS = previous.GUARDS + ("exclusive_alternative",)
SOURCE_KEYS = previous.SOURCE_KEYS
SEALED = ("fresh_targets", "annotation_ledger", "exposure_audit")
REQUIRED_FACETS = {
    "postmodal_condition": ("conditions",), "postmodal_exception": ("exceptions",),
    "postmodal_temporal": ("temporal",), "when_condition_front": ("conditions",),
    "on_condition_that_suffix": ("conditions",), "except_when_front": ("exceptions",),
    "suffix_condition": ("conditions",), "suffix_exception": ("exceptions",),
    "condition_prefix": ("conditions",), "temporal_suffix": ("temporal",),
    "condition_temporal_front": ("conditions", "temporal"),
    "exception_temporal_front": ("exceptions", "temporal"),
    "exception_condition_front": ("exceptions", "conditions"),
    "temporal_condition_postmodal": ("temporal", "conditions"),
    "exception_temporal_postmodal": ("exceptions", "temporal"),
    "exception_condition_postmodal": ("exceptions", "conditions"),
}


def values(panel, case, clause):
    require(panel in PREFIXES, "unknown boundary panel")
    name = f"{PREFIXES[panel]}{case:03d}x{clause}"
    modality = ("O", "P", "F")[(case + case // 6 + clause) % 3]
    return {"actor": ("{name} Records Office", "{name} Dept. of Records", "{name} Public Register Authority", "{name} Registry")[(case // 3 + clause) % 4].format(name=name),
        "action": ("retain", "inspect", "archive", "review", "publish", "submit")[(case // 6 + clause) % 6],
        "object": f"the {name.lower()} register",
        "conditions": f"the {name.lower()} permit is active", "exceptions": f"the {name.lower()} exemption is active",
        "temporal": f"within {31 + (case * 17 + clause * 13) % 431} days",
        "citation": f"section {9201 + case}.{clause + 2}", "modality": modality,
        "trigger": previous.MODALS[modality]}


def render(panel, case, family, clause=0):
    require(family in TRAIN_FAMILIES + FRESH_FAMILIES, "unknown construction family")
    v = values(panel, case, clause)
    required = set(REQUIRED_FACETS.get(family, ()))
    # Training and tuning include true absent facets. Fresh families each contain
    # exactly two qualifiers, leaving each third facet absent in one third of rows.
    present = set(required)
    if family not in FRESH_FAMILIES:
        mask = (case // 12 + clause) % 8
        present.update(f for bit, f in enumerate(FIELDS[3:]) if mask & (1 << bit))
    w = prior.CoordinateWriter()
    def field(name): w.add(v[name], name)
    def q(name, prefix, suffix=""):
        w.add(prefix); field(name); w.add(suffix)
    if family == "section_prefix" or (case // 12 + clause) % 4 == 1:
        w.add(f"Under {v['citation']}, ")
    prefix_done = set()
    fronts = {
        "condition_temporal_front": (("conditions", "If "), ("temporal", "")),
        "exception_temporal_front": (("exceptions", "Unless "), ("temporal", "")),
        "exception_condition_front": (("exceptions", "Except when "), ("conditions", "if ")),
        "when_condition_front": (("conditions", "When "),),
        "except_when_front": (("exceptions", "Except when "),),
        "condition_prefix": (("conditions", "If "),),
    }
    for f, cue in fronts.get(family, ()):
        q(f, cue, ", "); prefix_done.add(f)
    field("actor"); w.add(" "); field("trigger")
    post = {
        "postmodal_condition": ("conditions",), "postmodal_exception": ("exceptions",),
        "postmodal_temporal": ("temporal",),
        "temporal_condition_postmodal": ("temporal", "conditions"),
        "exception_temporal_postmodal": ("exceptions", "temporal"),
        "exception_condition_postmodal": ("exceptions", "conditions"),
    }
    inserted = set()
    for f in post.get(family, ()):
        q(f, {"conditions": ", if ", "exceptions": ", unless ", "temporal": ", "}[f]); inserted.add(f)
    if inserted: w.add(",")
    w.add(" "); field("action"); w.add(" "); field("object")
    for f, cue in (("temporal", " "), ("conditions", " on condition that " if family == "on_condition_that_suffix" else " if "), ("exceptions", " unless ")):
        if f in present and f not in prefix_done | inserted: q(f, cue)
    w.add(".")
    rule = {"modality": v["modality"], **{f: v[f] for f in FIELDS[:3]},
        **{f: [v[f]] if f in present else [] for f in FIELDS[3:]}}
    return mixed.validate_row({"id": "boundary-curriculum-clause-" + sha(w.text.encode())[:20],
        "source_text": w.text, "canonical_ir": {"rules": [rule]},
        "facet_spans": {f: w.spans.get(f) for f in FIELDS}, "trigger_span": w.spans["trigger"],
        "domain": "new", "trigger_supervised": True})


def authored_document(panel, ordinal):
    require(panel in COUNTS and 0 <= ordinal < COUNTS[panel], "invalid document panel/ordinal")
    supported = ordinal < SUPPORTED[panel]
    families = FRESH_FAMILIES if panel == "fresh" else TRAIN_FAMILIES
    family = families[ordinal % len(families)]
    count = 1 + (ordinal // len(families)) % 4 if supported else 2
    rendered = [render(panel, ordinal, family, c) for c in range(count)]
    repeated = supported and count >= 3 and (ordinal // (len(families) * 4)) % 2 == 0
    if repeated: rendered[2] = deepcopy(rendered[0])
    chunks, clauses, coordinates, cursor = [], [], [], 0
    for index, row in enumerate(rendered):
        text = row["source_text"]
        if index < count - 1 and ordinal % 3 == 0: text = text[:-1] + ";"
        separator = ("\n" if ordinal % 2 == 0 else " ") if index else ""
        cursor += len(separator); chunks.append(separator + text)
        clauses.append({"char_start": cursor, "char_end": cursor + len(text), "rule": row["canonical_ir"]["rules"][0]})
        coordinates.append({"clause_index": index, "char_start": cursor, "char_end": cursor + len(text),
            "facet_spans": {f: [x + cursor for x in span] if span else None for f, span in row["facet_spans"].items()},
            "trigger_span": [x + cursor for x in row["trigger_span"]], "family": family})
        cursor += len(text)
    text, reason = "".join(chunks), None
    if not supported:
        reason = GUARDS[(ordinal - SUPPORTED[panel]) % len(GUARDS)]
        first, second = [r["source_text"] for r in rendered]
        if reason == "shared_condition_prefix": text = "Both following rules share the same condition: " + first + " " + second
        elif reason == "coordinated_action": text = first[:-1] + " and publish the retained archive."
        elif reason == "exclusive_alternative": text = "Either " + first[:-1] + " or " + second
        else: text = first[:-1] + " unless " + second
        clauses, coordinates, repeated = [], [], False
    row = {"candidate_id": f"boundary-curriculum-{panel}-{ordinal:03d}", "source_text": text,
        "source_sha256": sha(text.encode()), "supported": supported,
        "construction": family if supported else "unsupported/" + reason,
        "repeated_rule_occurrences": repeated, "clauses": clauses, "unsupported_reason": reason,
        "label_origin": "new_authored_restricted_flat_profile_not_legal_authority"}
    annotation = {"candidate_id": row["candidate_id"], "source_sha256": row["source_sha256"],
        "panel": panel, "case_group": f"boundary-curriculum-{panel}-case-{ordinal:03d}",
        "family": family, "supported": supported, "guard": reason, "clause_coordinates": coordinates}
    return row, annotation


def validate_document(row, annotation=None):
    if row.get("unsupported_reason") == "exclusive_alternative":
        require(not row["supported"] and not row["clauses"] and documents.boundary.UNSUPPORTED.search(row["source_text"]), "exclusive scope guard invalid")
        require(sha(row["source_text"].encode()) == row["source_sha256"], "document source hash differs")
    else:
        previous.validate_document(row, annotation)
    documents.boundary.tokenize(row["source_text"])


def make_panels():
    panels, annotations = {}, []
    for panel, count in COUNTS.items():
        panels[panel] = []
        for ordinal in range(count):
            row, annotation = authored_document(panel, ordinal)
            validate_document(row, annotation)
            panels[panel].append(row); annotations.append(annotation)
    ledger = {"schema": "legal-boundary-curriculum-annotations/v1", "document_rows": annotations}
    validate_panels(panels, ledger)
    return panels, ledger


def validate_panels(panels, ledger):
    require({k: len(v) for k, v in panels.items()} == COUNTS, "panel counts differ")
    annotations = {a["candidate_id"]: a for a in ledger["document_rows"]}
    require(len(annotations) == sum(COUNTS.values()), "annotation identity coverage differs")
    texts, groups, ids = set(), set(), set()
    for panel, rows in panels.items():
        require(Counter(r["supported"] for r in rows) == {True: SUPPORTED[panel], False: COUNTS[panel] - SUPPORTED[panel]}, "support balance differs")
        require(Counter(r["unsupported_reason"] for r in rows if not r["supported"]) == {g: (COUNTS[panel] - SUPPORTED[panel]) // len(GUARDS) for g in GUARDS}, "guard balance differs")
        for row in rows:
            a = annotations[row["candidate_id"]]
            require(a["panel"] == panel and a["source_sha256"] == row["source_sha256"] and a["supported"] == row["supported"], "annotation binding differs")
            validate_document(row, a)
            normalized = prior.normalized_source(row["source_text"])
            require(normalized not in texts and a["case_group"] not in groups and row["candidate_id"] not in ids, "source/case/identity overlaps")
            texts.add(normalized); groups.add(a["case_group"]); ids.add(row["candidate_id"])
        rules = [c["rule"] for r in rows for c in r["clauses"]]
        require(set(r["modality"] for r in rules) == {"O", "P", "F"}, "all modal classes required")
        for f in FIELDS[3:]: require({bool(r[f]) for r in rules} == {True, False}, "present and absent facet classes required")


def load_prior_pools(previous_manifest_path):
    """Preparation-only exposure reconstruction, including already exposed labels."""
    pm = json.loads(Path(previous_manifest_path).read_bytes())
    require(pm["schema"] == previous.SCHEMA, "previous construction manifest required")
    inherited = temporal.load_training_inputs(pm["inputs"]["temporal_corpus"]["path"])
    tm = inherited["manifest"]; mm = read_ref(tm["inputs"]["mixed_corpus"])
    gm = read_ref(mm["inputs"]["new_curriculum"]); earlier = read_ref(mm["inputs"]["earlier_corpus"])
    pools = {"earlier_training": [r for r in inherited["training"]["baseline"] if r["domain"] == "earlier"],
        "new_training": [r for r in inherited["training"]["baseline"] if r["domain"] == "new"],
        "temporal_training": read_ref(tm["artifacts"]["temporal_training"]),
        **{name + "_tuning": rows for name, rows in inherited["tuning"].items()},
        "exposed_grounding150": [mixed.convert_new(r) for r in read_ref(gm["artifacts"]["challenge_targets"])],
        "exposed_mixed144": read_ref(mm["artifacts"]["challenge_targets"]),
        "exposed_temporal180": read_ref(tm["artifacts"]["challenge_targets"])}
    old_sources = {r["id"]: r for r in earlier["splits"]["challenge"]}
    pools["exposed_earlier192"] = [mixed.convert_earlier({**r, "source_text": old_sources[r["id"]]["source_text"]}) for r in read_ref(earlier["sealed_targets"])["targets"]]
    excluded = set(prior.extract_sources(earlier)); document_refs = pm["inputs"]["prior_document_references"]
    for split, reference in document_refs.items():
        rows = read_ref(reference); excluded.update(r["source_text"] for r in rows)
        pools["boundary_" + split + "_clauses"] = previous.document_clauses_for_audit(rows)
    for key in ("challenge_targets", "anchor_targets"):
        pools["exposed_construction_" + key] = read_ref(pm["artifacts"][key])
    for key in ("document_tuning_targets", "document_challenge_targets"):
        rows = read_ref(pm["artifacts"][key]); excluded.update(r["source_text"] for r in rows)
        pools["exposed_construction_" + key] = previous.document_clauses_for_audit(rows)
    for rows in pools.values(): excluded.update(r["source_text"] for r in rows)
    return pm, pools, excluded


def known_pool_references(pm):
    """Pin raw inputs plus explicit representation needed for independent audit."""
    tm = read_ref(pm["inputs"]["temporal_corpus"])
    mm = read_ref(tm["inputs"]["mixed_corpus"])
    gm = read_ref(mm["inputs"]["new_curriculum"])
    earlier = read_ref(mm["inputs"]["earlier_corpus"])
    refs = {name + "_training": {"reference": tm["artifacts"]["training_baseline"],
        "representation": "annotated_single", "filter_domain": name} for name in ("earlier", "new")}
    refs["temporal_training"] = {"reference": tm["artifacts"]["temporal_training"], "representation": "annotated_single"}
    for name in ("earlier", "prior_new", "temporal"):
        refs[name + "_tuning"] = {"reference": tm["artifacts"]["tuning_" + name], "representation": "annotated_single"}
    refs.update(exposed_grounding150={"reference": gm["artifacts"]["challenge_targets"], "representation": "grounding_single"},
        exposed_mixed144={"reference": mm["artifacts"]["challenge_targets"], "representation": "annotated_single"},
        exposed_temporal180={"reference": tm["artifacts"]["challenge_targets"], "representation": "annotated_single"},
        exposed_earlier192={"reference": earlier["sealed_targets"], "source_reference": mm["inputs"]["earlier_corpus"], "representation": "earlier_single_targets"})
    for split, reference in pm["inputs"]["prior_document_references"].items():
        refs["boundary_" + split + "_clauses"] = {"reference": reference, "representation": "document_clauses"}
    for key in ("challenge_targets", "anchor_targets", "document_tuning_targets", "document_challenge_targets"):
        refs["exposed_construction_" + key] = {"reference": pm["artifacts"][key], "representation": "document_clauses" if key.startswith("document_") else "annotated_single"}
    return refs


def freeze(output, previous_manifest_path=DEFAULT_PREVIOUS):
    output = Path(output).resolve(); require(not output.exists(), "output already exists")
    pm, known, excluded = load_prior_pools(previous_manifest_path)
    panels, ledger = make_panels()
    previous.verify_disjoint(panels, excluded)
    known["new_boundary_training_clauses"] = previous.document_clauses_for_audit(panels["train"])
    known["new_boundary_tuning_clauses"] = previous.document_clauses_for_audit(panels["tuning"])
    layouts = {name: {previous.generic_layout(row) for row in rows} for name, rows in known.items()}
    evidence = []
    for row in previous.document_clauses_for_audit(panels["fresh"]):
        layout = previous.generic_layout(row)
        matches = sorted(name for name, shapes in layouts.items() if layout in shapes)
        require(not matches, "fresh clause construction already exposed")
        evidence.append({"id": row["id"], "source_sha256": sha(row["source_text"].encode()), "role_masked_layout": layout, "matching_pools": matches})
    # Split novelty is assessed for supported clause grammar only. Guard wrappers
    # intentionally recur; lexical case identities and source texts remain new.
    exposure = {"schema": "legal-boundary-curriculum-exposure/v1", "fresh_clause_evidence": evidence,
        "known_role_masked_layouts": {name: sorted(shapes) for name, shapes in layouts.items()},
        "known_pool_counts": {name: len(rows) for name, rows in known.items()},
        "method": "Authored facet spans masked; modal spelling, numbers, citation letters and terminal punctuation normalized by pinned previous.generic_layout. All pinned local admitted/exposed inventories plus new training/tuning are compared.",
        "fresh_clause_layout_matches": 0, "guard_wrapper_novelty_claimed": False,
        "claim": "Six held-out combinations of qualifier positions relative to pinned known local inventories; no universal language or pretraining novelty claim."}
    summary = {}
    for panel, rows in panels.items():
        rules = [c["rule"] for r in rows for c in r["clauses"]]
        summary[panel] = {"documents": len(rows), "supported": SUPPORTED[panel], "guards": len(rows)-SUPPORTED[panel],
            "clause_occurrences": len(rules), "modality_counts": dict(Counter(r["modality"] for r in rules)),
            "facet_present": {f: sum(bool(r[f]) for r in rules) for f in FIELDS[3:]},
            "facet_absent": {f: sum(not r[f] for r in rules) for f in FIELDS[3:]},
            "repeated_documents": sum(r["repeated_rule_occurrences"] for r in rows),
            "max_source_tokens": max(len(documents.boundary.tokenize(r["source_text"])) for r in rows)}
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {"new_training_targets": write_new(output / "new-training-targets.json", panels["train"]),
        "original_replay_targets": pm["inputs"]["prior_document_references"]["train"],
        "tuning_sources": write_new(output / "tuning-sources.json", [previous.document_source(r) for r in panels["tuning"]]),
        "tuning_targets": write_new(output / "tuning-targets.json", panels["tuning"]),
        "fresh_sources": write_new(output / "fresh-sources.json", [previous.document_source(r) for r in panels["fresh"]]),
        "fresh_targets": write_new(output / "fresh-targets.sealed.json", panels["fresh"]),
        "annotation_ledger": write_new(output / "annotations.sealed.json", ledger)}
    pool_refs = known_pool_references(pm)
    pool_refs["new_boundary_training_clauses"] = {"reference": artifacts["new_training_targets"], "representation": "document_clauses"}
    pool_refs["new_boundary_tuning_clauses"] = {"reference": artifacts["tuning_targets"], "representation": "document_clauses"}
    require(set(pool_refs) == set(known), "known pool provenance inventory differs")
    exposure["known_pool_references"] = pool_refs
    artifacts["exposure_audit"] = write_new(output / "exposure-audit.sealed.json", exposure)
    manifest = {"schema": SCHEMA, "artifacts": artifacts, "generator": file_ref(__file__),
        "dependencies": {name: file_ref(module.__file__) for name, module in (("previous", previous), ("temporal", temporal), ("mixed", mixed), ("coordinates", prior), ("documents", documents), ("boundary", documents.boundary), ("composition", documents.compose))},
        "inputs": {"previous_corpus": file_ref(previous_manifest_path)}, "counts": summary,
        "frozen_before_training": True, "training_performed": False, "training_rows_added": 384,
        "qualified": False, "provenance": "authored_synthetic_not_legal_authority", "sealed_during_training": list(SEALED),
        "training_families": list(TRAIN_FAMILIES), "fresh_families": list(FRESH_FAMILIES),
        "source_overlap_audit": {"unique_excluded_texts": len(excluded), "normalized_source_or_clause_overlaps": 0,
            "scope": "All pinned local earlier/new/temporal/construction singles, boundary and construction documents and supported clause sources."},
        "construction_exposure_summary": {"fresh_clause_layout_matches": 0, "fresh_clause_occurrences": len(evidence),
            "known_pool_counts": exposure["known_pool_counts"], "scope": exposure["claim"]},
        "semantics": {"conditions": "Opaque externally valued applicability atoms; if, when and on condition that are equivalent in this restricted authored grammar.",
            "exceptions": "Unless and except when are equivalent rule-level exceptions; multiple qualifiers belong to this one rule, never a neighboring rule.",
            "temporal": "within N days is the action temporal limit under the prior activation-anchor convention for O/P/F. Front and postmodal comma placement do not change its scope.",
            "citations": "Under section N.M is source metadata, excluded from canonical rule atoms; decimal periods and Dept. abbreviations are not clause boundaries.",
            "guards": "Shared scope, action coordination, nested normative exception and exclusive alternatives have no admitted flat target.",
            "fresh_absence": "Each held-out family contains exactly two of condition/exception/action-time; each facet is absent in one third of fresh supported clauses. No fresh all-absent cohort."},
        "limitations": ["Synthetic controlled semantics without independent statutory review.", "The six new families are qualifier-order combinations; generalization beyond these combinations remains untested.", "Guard wrapper classes deliberately repeat training.", "Source-only inference must not open labels or occurrence/layout evidence.", "No clause-decoder, latent-encoder or all-logic-family training performed by this corpus generator."]}
    return write_new(output / "manifest.json", manifest)


def load_training_inputs(manifest_path):
    """Read admitted train/tuning labels and source-only fresh rows; no sealed IO."""
    manifest = json.loads(Path(manifest_path).read_bytes())
    require(manifest.get("schema") == SCHEMA and manifest.get("frozen_before_training") is True, "frozen boundary curriculum manifest required")
    verify_ref(manifest["generator"])
    for reference in manifest["dependencies"].values(): verify_ref(reference)
    artifacts = manifest["artifacts"]
    new_train = read_ref(artifacts["new_training_targets"])
    replay = read_ref(artifacts["original_replay_targets"])
    tuning = read_ref(artifacts["tuning_targets"])
    tuning_sources = read_ref(artifacts["tuning_sources"])
    fresh_sources = read_ref(artifacts["fresh_sources"])
    require((len(new_train), len(replay), len(tuning), len(fresh_sources)) == (384, 192, 96, 96), "admitted input counts differ")
    require([previous.document_source(r) for r in tuning] == tuning_sources, "tuning source identity/order differs")
    for rows, count in ((new_train, 288), (tuning, 72)):
        require(sum(r["supported"] is True for r in rows) == count, "admitted support denominator differs")
        for row in rows: validate_document(row)
    for row in replay: documents.boundary.tokenize(row["source_text"])
    for row in tuning_sources + fresh_sources:
        require(set(row) == SOURCE_KEYS and sha(row["source_text"].encode()) == row["source_sha256"], "closed source-only schema/hash required")
    allrows = new_train + replay + tuning + fresh_sources
    require(len({prior.normalized_source(r["source_text"]) for r in allrows}) == len(allrows), "admitted source panels overlap")
    require(len({r["candidate_id"] for r in allrows}) == len(allrows), "admitted source identities overlap")
    return {"manifest": manifest, "new_train": new_train, "replay": replay, "new_tuning": tuning, "fresh_sources": fresh_sources}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--previous-manifest", type=Path, default=DEFAULT_PREVIOUS)
    args = parser.parse_args()
    print(json.dumps(freeze(args.output, args.previous_manifest), sort_keys=True))


if __name__ == "__main__": main()
