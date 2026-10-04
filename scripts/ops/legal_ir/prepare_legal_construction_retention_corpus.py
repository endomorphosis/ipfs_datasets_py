#!/usr/bin/env python3
"""Freeze construction holdouts and independent document tuning; perform no fit.

Fresh labels and coordinate-derived novelty evidence are separate, embargoed
artifacts. Only document tuning and inherited single-rule tuning are admitted
to checkpoint selection. Each fresh single-rule case has six equivalent forms.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_temporal_curriculum as temporal
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as documents

mixed, prior = temporal.mixed, temporal.prior
FIELDS = prior.FIELDS
sha, canonical_bytes = prior.sha, prior.canonical_bytes
file_ref, read_ref, verify_ref, write_new = prior.file_ref, prior.read_ref, prior.verify_ref, prior.write_new
SCHEMA = "legal-construction-retention-corpus/v1"
DEFAULT_TEMPORAL = prior.ARTIFACTS / "legal-decoder-temporal-curriculum-20261002/corpus-01/manifest.json"
FAMILIES = ("postmodal_condition", "postmodal_exception", "postmodal_temporal",
    "when_condition_front", "on_condition_that_suffix", "except_when_front")
TUNING_FAMILIES = ("plain", "suffix_condition", "suffix_exception", "condition_prefix", "section_prefix", "temporal_suffix")
GUARDS = ("shared_condition_prefix", "coordinated_action", "nested_normative_exception")
SEALED = ("challenge_targets", "anchor_targets", "document_challenge_targets", "annotation_ledger", "exposure_audit", "novelty_evidence")
SOURCE_KEYS = {"candidate_id", "source_text", "source_sha256"}
PREFIXES = {"single": "Celandine", "document_tuning": "Foxglove", "document_challenge": "Meadowsweet"}
ACTORS = ("{name} Records Office", "{name} Public Register Authority", "{name} Registry", "{name} Dept. of Records")
MODALS = {"O": "must", "P": "may", "F": "must not"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def values(panel, case, clause=0):
    """Independent authored identities and deterministic slot assignments."""
    require(panel in PREFIXES, "unknown panel")
    name = f"{PREFIXES[panel]}{case:03d}x{clause}"
    group = case if panel == "single" else case // 6
    modality = ("O", "P", "F")[(group + clause) % 3]
    number = random.Random(f"construction-retention/v1:{panel}:{case}:{clause}").randrange(17, 490)
    return {"actor": ACTORS[(case // 3 + clause) % len(ACTORS)].format(name=name),
        "action": ("inspect", "retain", "submit", "archive", "review", "publish")[(group // 3 + group % 3 + clause) % 6],
        "object": f"the {name.lower()} register",
        "conditions": f"the {name.lower()} permit is active",
        "exceptions": f"the {name.lower()} exemption is active",
        "temporal": f"within {number} days", "citation": f"section {6401 + number}(a)",
        "modality": modality, "trigger": MODALS[modality]}


def render(panel, case, family, clause=0):
    require(family in FAMILIES + TUNING_FAMILIES + ("seen_layout_anchor",), "unsupported rendering family")
    v = values(panel, case, clause)
    writer = prior.CoordinateWriter()

    def field(name):
        writer.add(v[name], name)

    def atom(name, prefix="", suffix=""):
        writer.add(prefix); field(name); writer.add(suffix)

    if family == "when_condition_front":
        atom("conditions", "When ", ", ")
    elif family == "except_when_front":
        atom("exceptions", "Except when ", ", ")
    elif family == "condition_prefix":
        atom("conditions", "If ", ", ")
    elif family == "section_prefix":
        writer.add(f"Under {v['citation']}, ")
    field("actor"); writer.add(" "); field("trigger")
    inserted = {"postmodal_condition": "conditions", "postmodal_exception": "exceptions", "postmodal_temporal": "temporal"}.get(family)
    if inserted:
        atom(inserted, {"conditions": ", if ", "exceptions": ", unless ", "temporal": ", "}[inserted], ",")
    writer.add(" "); field("action"); writer.add(" "); field("object")
    if family in FAMILIES or family == "seen_layout_anchor":
        if inserted != "temporal":
            atom("temporal", " ")
        if "conditions" not in writer.spans:
            atom("conditions", " on condition that " if family == "on_condition_that_suffix" else " if ")
        if "exceptions" not in writer.spans:
            atom("exceptions", " unless ")
    elif family == "suffix_condition":
        atom("conditions", " if ")
    elif family == "suffix_exception":
        atom("exceptions", " unless ")
    elif family == "temporal_suffix":
        atom("temporal", " ")
    writer.add(".")
    rule = {"modality": v["modality"], **{f: v[f] for f in FIELDS[:3]},
        **{f: [v[f]] if f in writer.spans else [] for f in FIELDS[3:]}}
    return mixed.validate_row({"id": "construction-" + panel + "-" + sha(writer.text.encode())[:20],
        "source_text": writer.text, "canonical_ir": {"rules": [rule]},
        "facet_spans": {f: writer.spans.get(f) for f in FIELDS}, "trigger_span": writer.spans["trigger"],
        "domain": "new", "trigger_supervised": True})


def document_source(row):
    return {k: row[k] for k in ("candidate_id", "source_text", "source_sha256")}


def authored_document(panel, ordinal):
    require(panel in {"document_tuning", "document_challenge"}, "unknown document panel")
    family = (TUNING_FAMILIES if panel == "document_tuning" else FAMILIES)[ordinal % 6]
    supported = ordinal < 72
    count = 1 + (ordinal // 6) % 4 if supported else 2
    rendered = [render(panel, ordinal, family, i) for i in range(count)]
    repeated = supported and count >= 3 and (ordinal // 24) % 2 == 0
    if repeated:
        rendered[2] = deepcopy(rendered[0])
    cursor, chunks, clauses, coordinates = 0, [], [], []
    for index, row in enumerate(rendered):
        text = row["source_text"]
        if index < count - 1 and (ordinal // 6) % 2 == 0:
            text = text[:-1] + ";"
        separator = ("\n" if ordinal % 2 == 0 else " ") if index else ""
        cursor += len(separator)
        chunks.append(separator + text)
        clauses.append({"char_start": cursor, "char_end": cursor + len(text), "rule": row["canonical_ir"]["rules"][0]})
        coordinates.append({"clause_index": index, "char_start": cursor, "char_end": cursor + len(text),
            "facet_spans": {k: [v[0] + cursor, v[1] + cursor] if v else None for k, v in row["facet_spans"].items()},
            "trigger_span": [x + cursor for x in row["trigger_span"]], "family": family})
        cursor += len(text)
    text, reason = "".join(chunks), None
    if not supported:
        reason = GUARDS[((ordinal - 72) // 6) % 3]
        first, second = [r["source_text"] for r in rendered]
        if reason == "shared_condition_prefix":
            text = "Both following rules share the same condition: " + first + " " + second
        elif reason == "coordinated_action":
            text = first[:-1] + " and publish the retained archive."
        else:
            text = first[:-1] + " unless " + second
        clauses, coordinates, repeated = [], [], False
    row = {"candidate_id": f"construction-{panel}-{ordinal:03d}", "source_text": text,
        "source_sha256": sha(text.encode()), "supported": supported,
        "construction": family if supported else "unsupported/" + reason,
        "repeated_rule_occurrences": repeated, "clauses": clauses, "unsupported_reason": reason,
        "label_origin": "new_authored_restricted_flat_profile_not_legal_authority"}
    return row, {"candidate_id": row["candidate_id"], "source_sha256": row["source_sha256"],
        "panel": panel, "case_group": f"construction-{panel}-case-{ordinal:03d}",
        "family": family, "supported": supported, "guard": reason, "clause_coordinates": coordinates}


def make_panels():
    singles, single_ledger, anchors, anchor_ledger = [], [], [], []
    for case in range(30):
        for family in FAMILIES:
            row = render("single", case, family)
            singles.append(row)
            single_ledger.append({"id": row["id"], "source_sha256": sha(row["source_text"].encode()),
                "panel": "single", "case_group": f"construction-single-case-{case:03d}", "family": family,
                "facet_spans": row["facet_spans"], "trigger_span": row["trigger_span"]})
        anchor = render("single", case, "seen_layout_anchor")
        anchors.append(anchor)
        anchor_ledger.append({"id": anchor["id"], "source_sha256": sha(anchor["source_text"].encode()),
            "panel": "anchor", "case_group": f"construction-single-case-{case:03d}", "family": "seen_layout_anchor",
            "facet_spans": anchor["facet_spans"], "trigger_span": anchor["trigger_span"]})
    docs, doc_ledger = {}, []
    for panel in ("document_tuning", "document_challenge"):
        docs[panel] = []
        for i in range(96):
            row, annotation = authored_document(panel, i)
            docs[panel].append(row); doc_ledger.append(annotation)
    panels = {"single": singles, "anchor": anchors, **docs}
    ledger = {"schema": "legal-construction-retention-annotations/v1", "single_rows": single_ledger,
        "anchor_rows": anchor_ledger, "document_rows": doc_ledger}
    validate_panels(panels, ledger)
    return panels, ledger


def validate_document(row, annotation=None):
    text = row["source_text"]
    require(sha(text.encode()) == row["source_sha256"], "document source hash differs")
    if not row["supported"]:
        require(not row["clauses"] and row["unsupported_reason"] in GUARDS, "unsupported scope must not invent clauses")
        require(documents.boundary.UNSUPPORTED.search(text) or
            row["unsupported_reason"] == "nested_normative_exception" and len(documents.boundary.MODAL.findall(text)) > 1,
            "scope guard fixture lacks declared surface or nested-modal policy")
        return
    require(row["unsupported_reason"] is None and bool(row["clauses"]), "supported document requires clauses")
    require(not documents.boundary.UNSUPPORTED.search(text), "supported document accidentally triggers unsupported policy")
    plan = [{"clause_id": f"authored-{i}", "char_start": c["char_start"], "char_end": c["char_end"],
        "scope": documents.compose.FLAT_SCOPE} for i, c in enumerate(row["clauses"])]
    documents.compose.prepare_source_plan(document_source(row), plan)
    if annotation:
        require(annotation["source_sha256"] == row["source_sha256"], "document annotation hash differs")
        require(len(annotation["clause_coordinates"]) == len(row["clauses"]), "document coordinate count differs")
        for clause, coords in zip(row["clauses"], annotation["clause_coordinates"]):
            start, end = clause["char_start"], clause["char_end"]
            require((start, end) == (coords["char_start"], coords["char_end"]), "document clause coordinates differ")
            require(len(documents.boundary.MODAL.findall(text[start:end])) == 1, "supported clause needs one recognized modal")
            local = {"id": "coordinate-audit", "source_text": text[start:end], "canonical_ir": {"rules": [clause["rule"]]},
                "facet_spans": {f: [v[0] - start, v[1] - start] if v else None for f, v in coords["facet_spans"].items()},
                "trigger_span": [v - start for v in coords["trigger_span"]], "domain": "new", "trigger_supervised": True}
            mixed.validate_row(local)


def validate_panels(panels, ledger):
    require({k: len(v) for k, v in panels.items()} == {"single": 180, "anchor": 30, "document_tuning": 96, "document_challenge": 96}, "panel counts differ")
    by_id = {a["id"]: a for a in ledger["single_rows"]}
    require(len(by_id) == 180, "single annotation inventory differs")
    groups = {}
    for row in panels["single"]:
        mixed.validate_row(row)
        a = by_id[row["id"]]
        require(a["source_sha256"] == sha(row["source_text"].encode()) and a["facet_spans"] == row["facet_spans"] and a["trigger_span"] == row["trigger_span"], "single annotation binding differs")
        groups.setdefault(a["case_group"], []).append((row, a))
    require(len(groups) == 30, "single case group count differs")
    for records in groups.values():
        require(Counter(a["family"] for _, a in records) == Counter(FAMILIES), "six unique constructions per case required")
        require(all(r["canonical_ir"] == records[0][0]["canonical_ir"] for r, _ in records), "single case meanings differ")
    anchors = {r["id"]: r for r in panels["anchor"]}
    require(len(anchors) == 30 and len(ledger["anchor_rows"]) == 30, "anchor inventory differs")
    require({a["case_group"] for a in ledger["anchor_rows"]} == set(groups), "anchor case coverage differs")
    for a in ledger["anchor_rows"]:
        row = anchors[a["id"]]
        mixed.validate_row(row)
        require(a["family"] == "seen_layout_anchor" and a["source_sha256"] == sha(row["source_text"].encode()) and
            a["facet_spans"] == row["facet_spans"] and a["trigger_span"] == row["trigger_span"], "anchor annotation binding differs")
        require(row["canonical_ir"] == groups[a["case_group"]][0][0]["canonical_ir"], "anchor meaning differs from matched case")
    annotations = {a["candidate_id"]: a for a in ledger["document_rows"]}
    require(len(annotations) == 192, "document annotation inventory differs")
    for panel in ("document_tuning", "document_challenge"):
        require(Counter(r["supported"] for r in panels[panel]) == {True: 72, False: 24}, "document support denominators differ")
        for row in panels[panel]:
            a = annotations[row["candidate_id"]]
            require(a["panel"] == panel and a["source_sha256"] == row["source_sha256"], "document annotation panel differs")
            validate_document(row, a)
    allrows = [r for rows in panels.values() for r in rows]
    require(len({prior.normalized_source(r["source_text"]) for r in allrows}) == len(allrows), "new panel sources overlap")
    case_sets = [set(groups)] + [{a["case_group"] for a in ledger["document_rows"] if a["panel"] == panel} for panel in ("document_tuning", "document_challenge")]
    require(not any(left & right for i, left in enumerate(case_sets) for right in case_sets[i + 1:]), "case groups cross panels")


def document_clauses_for_audit(rows):
    """Recover only unique atom occurrences inside already authored old clauses.

    This exposure-only helper never supplies inference boundaries or fit labels.
    New document coordinates are independently emitted during construction.
    """
    result = []
    for row in rows:
        for index, clause in enumerate(row["clauses"]):
            text = row["source_text"][clause["char_start"]:clause["char_end"]]
            spans = {}
            for field in FIELDS:
                atom = clause["rule"][field]
                if field in FIELDS[3:]:
                    require(len(atom) <= 1, "exposure audit only supports single atoms")
                    atom = atom[0] if atom else None
                if atom is None:
                    spans[field] = None
                else:
                    matches = list(re.finditer(re.escape(atom), text))
                    require(len(matches) == 1, "ambiguous historical exposure coordinate")
                    spans[field] = [matches[0].start(), matches[0].end()]
            result.append({"id": f"{row['candidate_id']}-clause-{index}", "source_text": text, "facet_spans": spans})
    return result


def generic_layout(row):
    """Remove modal spelling too, making holdout audit stricter than exact shape."""
    value = mixed.skeleton(row)
    for phrase in sorted(prior.TRIGGER_MEANINGS, key=len, reverse=True):
        value = re.sub(r"\b" + re.escape(phrase) + r"\b", "<modal>", value)
    return value.rstrip(".;")


def verify_disjoint(panels, excluded):
    normalized = {prior.normalized_source(s) for s in excluded}
    checked = []
    for panel, rows in panels.items():
        for row in rows:
            checked.append(row["source_text"])
            if panel not in {"single", "anchor"}:
                checked.extend(row["source_text"][c["char_start"]:c["char_end"]] for c in row["clauses"])
    require(all(prior.normalized_source(s) not in normalized for s in checked), "new source or clause overlaps prior pool")


def freeze(output, temporal_manifest_path=DEFAULT_TEMPORAL):
    output = Path(output).resolve()
    require(not output.exists(), "output already exists")
    inherited = temporal.load_training_inputs(temporal_manifest_path)
    tm = inherited["manifest"]
    mm = read_ref(tm["inputs"]["mixed_corpus"])
    gm = read_ref(mm["inputs"]["new_curriculum"])
    earlier = read_ref(mm["inputs"]["earlier_corpus"])
    pools = {"earlier_training": [r for r in inherited["training"]["baseline"] if r["domain"] == "earlier"],
        "new_training": [r for r in inherited["training"]["baseline"] if r["domain"] == "new"],
        "temporal_training": read_ref(tm["artifacts"]["temporal_training"]),
        **{name + "_tuning": rows for name, rows in inherited["tuning"].items()}}
    admitted = set(pools)
    pools.update(exposed_grounding150=[mixed.convert_new(r) for r in read_ref(gm["artifacts"]["challenge_targets"])],
        exposed_mixed144=read_ref(mm["artifacts"]["challenge_targets"]),
        exposed_temporal180=read_ref(tm["artifacts"]["challenge_targets"]))
    old_sources = {r["id"]: r for r in earlier["splits"]["challenge"]}
    oldtargets = read_ref(earlier["sealed_targets"])["targets"]
    pools["exposed_earlier192"] = [mixed.convert_earlier({**r, "source_text": old_sources[r["id"]]["source_text"]}) for r in oldtargets]
    document_refs = {}
    for split in ("train", "tuning", "test"):
        reference = file_ref(temporal.DOC_BASE / (split + "-references.json"))
        rows = read_ref(reference)
        document_refs[split] = reference
        pools["boundary_" + split + "_clauses"] = document_clauses_for_audit(rows)
        if split == "train":
            admitted.add("boundary_train_clauses")
    panels, ledger = make_panels()
    excluded = set(prior.extract_sources(earlier))
    for rows in pools.values():
        excluded.update(r["source_text"] for r in rows)
    for reference in document_refs.values():
        excluded.update(prior.extract_sources(read_ref(reference)))
    verify_disjoint(panels, excluded)
    layouts = {name: {generic_layout(r) for r in rows} for name, rows in pools.items()}
    single_annotations = {a["id"]: a for a in ledger["single_rows"]}
    evidence = []
    for row in panels["single"]:
        layout = generic_layout(row)
        matches = [name for name, known in layouts.items() if layout in known]
        require(not matches, "fresh construction overlaps known admitted/exposed layout")
        evidence.append({"id": row["id"], "source_sha256": sha(row["source_text"].encode()),
            "family": single_annotations[row["id"]]["family"], "role_masked_layout": layout, "matching_pools": matches})
    anchor_evidence = []
    anchor_annotations = {a["id"]: a for a in ledger["anchor_rows"]}
    for row in panels["anchor"]:
        matches = sorted(name for name in admitted if generic_layout(row) in layouts[name])
        require(any("training" in name or name == "boundary_train_clauses" for name in matches), "anchor layout must be represented in training")
        anchor_evidence.append({"id": row["id"], "source_sha256": sha(row["source_text"].encode()),
            "case_group": anchor_annotations[row["id"]]["case_group"], "family": "seen_layout_anchor",
            "role_masked_layout": generic_layout(row), "matching_admitted_pools": matches})
    tuning_clauses = document_clauses_for_audit(panels["document_tuning"])
    tuning_matches = []
    for row in tuning_clauses:
        matches = sorted(name for name in admitted if generic_layout(row) in layouts[name])
        require(matches, "document tuning construction not present in an admitted training/tuning pool")
        # Require real training exposure, not merely inherited tuning exposure.
        require(any("training" in name or name == "boundary_train_clauses" for name in matches), "document tuning family has no training exposure")
        tuning_matches.append({"id": row["id"], "role_masked_layout": generic_layout(row), "matching_admitted_pools": matches})
    fresh_doc_clauses = document_clauses_for_audit(panels["document_challenge"])
    for row in fresh_doc_clauses:
        require(not any(generic_layout(row) in known for known in layouts.values()), "fresh document clause repeats known layout")
    generator_names = ("prepare_legal_span_experiment.py", "prepare_legal_grounding_curriculum.py",
        "prepare_legal_mixed_replay_corpus.py", "prepare_legal_temporal_curriculum.py", "run_legal_clause_boundary_experiment.py")
    generators = {name: file_ref(Path(__file__).parent / name) for name in generator_names}
    exposure = {"schema": "legal-construction-retention-exposure/v1", "single_rows": evidence, "anchor_rows": anchor_evidence,
        "document_tuning_clause_exposure": tuning_matches,
        "known_pool_counts": {name: len(rows) for name, rows in pools.items()},
        "known_role_masked_layouts": {name: sorted(shapes) for name, shapes in layouts.items()},
        "method": "Mask exact authored facet coordinates, normalize numbers and citation letters, collapse every admitted modal phrase to <modal>, normalize terminal period/semicolon. Compare all pinned admitted local training/tuning and known exposed evaluation layouts. Historical document atom coordinates require a unique match inside already authored clause bounds; never used in inference.",
        "fresh_single_exact_layout_matches": 0, "fresh_document_clause_exact_layout_matches": 0,
        "claim": "Six locally held-out authored rendering families relative to the pinned pools and inspected cumulative generators, not universal language-model pretraining novelty or independent legal semantics.",
        "fresh_scope_guards": "Unsupported wrapper types are inherited intentionally; only their underlying held-out clause forms and case identities are new. No unsupported AST or wrapper novelty claim."}
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {"tuning_" + k: write_new(output / ("tuning-" + k.replace("_", "-") + ".json"), rows) for k, rows in inherited["tuning"].items()}
    artifacts.update(document_tuning_sources=write_new(output / "document-tuning-sources.json", [document_source(r) for r in panels["document_tuning"]]),
        document_tuning_targets=write_new(output / "document-tuning-targets.json", panels["document_tuning"]),
        challenge_sources=write_new(output / "challenge-sources.json", [{k: r[k] for k in ("id", "source_text")} for r in panels["single"]]),
        challenge_targets=write_new(output / "challenge-targets.sealed.json", panels["single"]),
        anchor_sources=write_new(output / "anchor-sources.json", [{k: r[k] for k in ("id", "source_text")} for r in panels["anchor"]]),
        anchor_targets=write_new(output / "anchor-targets.sealed.json", panels["anchor"]),
        document_challenge_sources=write_new(output / "document-challenge-sources.json", [document_source(r) for r in panels["document_challenge"]]),
        document_challenge_targets=write_new(output / "document-challenge-targets.sealed.json", panels["document_challenge"]),
        annotation_ledger=write_new(output / "annotations.sealed.json", ledger),
        exposure_audit=write_new(output / "exposure-audit.sealed.json", exposure),
        novelty_evidence=write_new(output / "novelty-evidence.sealed.json", {"schema": "legal-construction-novelty-evidence/v1", "rows": evidence, "anchor_rows": anchor_evidence,
            "coordinate_derived_reference_evidence": True, "embargo": "No selection or generation reads before qualification build freeze."}))
    manifest = {"schema": SCHEMA, "artifacts": artifacts, "generator": file_ref(__file__),
        "dependencies": {"temporal_helpers": file_ref(temporal.__file__), "mixed_helpers": file_ref(mixed.__file__), "coordinate_helpers": file_ref(prior.__file__),
            "document_helpers": file_ref(documents.__file__), "boundary": file_ref(documents.boundary.__file__), "composition": file_ref(documents.compose.__file__)},
        "inputs": {"temporal_corpus": file_ref(temporal_manifest_path), "prior_document_references": document_refs, "reviewed_cumulative_generators": generators},
        "counts": {"tuning_earlier": 96, "tuning_prior_new": 96, "tuning_temporal": 120, "tuning_total": 312,
            "document_tuning": 96, "document_tuning_supported": 72, "document_tuning_unsupported": 24,
            "challenge": 180, "challenge_case_groups": 30, "anchors": 30, "document_challenge": 96,
            "document_challenge_supported": 72, "document_challenge_unsupported": 24},
        "frozen_before_selection": True, "training_performed": False, "training_rows_added": 0,
        "qualified": False, "provenance": "authored_synthetic_not_legal_authority",
        "heldout_families": list(FAMILIES), "document_tuning_families": list(TUNING_FAMILIES),
        "sealed_during_selection": list(SEALED),
        "source_overlap_audit": {"unique_excluded_texts": len(excluded), "normalized_source_or_clause_overlaps": 0,
            "scope": "All pinned admitted and exposed prior single-rule sources, old diagnostic sources, document sources and supported reference clauses; all three newly authored panels also source-disjoint."},
        "construction_exposure_summary": {"fresh_single_layout_matches": 0, "fresh_document_clause_layout_matches": 0,
            "all_document_tuning_clauses_have_verified_training_layout_exposure": True,
            "all_30_matched_anchor_layouts_have_verified_training_exposure": True,
            "known_pool_counts": exposure["known_pool_counts"], "scope": exposure["claim"]},
        "semantics": {"when": "When C and on condition that C mean applicability exactly when the externally valued opaque condition C is true; no event timing or calendar relation is inferred.",
            "except_when": "Except when E means the same rule-level exception as unless E; E remains an opaque externally valued atom.",
            "temporal": "within N days is an action temporal limit under the previously declared activation-anchor policy: obligation deadline O, bounded permission P, temporal prohibition F.",
            "postmodal_parentheticals": "Commas delimit a rule-level condition, exception, or action temporal limit after must/may/must not. Multiword infinitival modal paraphrases are excluded.",
            "fresh_single_cohort": "All six forms preserve all facets and have condition, exception and action temporal facets present. This fresh cohort cannot establish absent-facet false-positive performance.",
            "matched_anchors": "Each of the 30 test case groups also has one ordinary seen-layout anchor with identical canonical IR, separating new case identity from rendering effects. Anchors share cases only within the test cohort; never with tuning.",
            "unsupported": "Shared scope, coordinated actions and nested normative exceptions receive no flat clauses or fabricated logical targets."},
        "case_groups": {"single": sorted({r["case_group"] for r in ledger["single_rows"]}),
            **{p: sorted({r["case_group"] for r in ledger["document_rows"] if r["panel"] == p}) for p in ("document_tuning", "document_challenge")}},
        "limitations": ["Controlled authored language, not statutory authority.", "Fresh document scope-guard wrapper types deliberately recur from prior boundary training.",
            "Case variants are correlated; use group-level denominators.", "Reference coordinates never choose learned document segmentation.",
            "No universal pretraining novelty, calendar arithmetic or full logic-family correctness claim.", "Separate target artifacts are an access protocol, not encryption."]}
    return write_new(output / "manifest.json", manifest)


def load_selection_inputs(manifest_path):
    """Read admitted labels and raw fresh sources only, never sealed bytes."""
    manifest = json.loads(Path(manifest_path).read_bytes())
    require(manifest.get("schema") == SCHEMA and manifest.get("frozen_before_selection") is True, "frozen construction manifest required")
    verify_ref(manifest["generator"])
    for reference in manifest["dependencies"].values():
        verify_ref(reference)
    artifacts = manifest["artifacts"]
    allowed = ("tuning_earlier", "tuning_prior_new", "tuning_temporal", "document_tuning_sources", "document_tuning_targets", "challenge_sources", "anchor_sources", "document_challenge_sources")
    loaded = {key: read_ref(artifacts[key]) for key in allowed}
    for key, count in (("tuning_earlier", 96), ("tuning_prior_new", 96), ("tuning_temporal", 120), ("document_tuning_sources", 96), ("document_tuning_targets", 96), ("challenge_sources", 180), ("anchor_sources", 30), ("document_challenge_sources", 96)):
        require(len(loaded[key]) == count, "selection input count differs")
    for key in allowed[:3]:
        for row in loaded[key]:
            mixed.validate_row(row)
    for row in loaded["challenge_sources"] + loaded["anchor_sources"]:
        require(set(row) == {"id", "source_text"}, "fresh single input contains reference fields")
    for key in ("document_tuning_sources", "document_challenge_sources"):
        for row in loaded[key]:
            require(set(row) == SOURCE_KEYS and sha(row["source_text"].encode()) == row["source_sha256"], "document source input schema/hash differs")
    targets = loaded["document_tuning_targets"]
    require([document_source(r) for r in targets] == loaded["document_tuning_sources"], "document tuning source/target order or binding differs")
    require(Counter(r["supported"] for r in targets) == {True: 72, False: 24}, "document tuning denominators differ")
    for row in targets:
        validate_document(row)
    allrows = [r for key in allowed if key != "document_tuning_targets" for r in loaded[key]]
    require(len({prior.normalized_source(r["source_text"]) for r in allrows}) == len(allrows), "selection panels source overlap")
    return {"manifest": manifest, "tuning": {name: loaded["tuning_" + name] for name in ("earlier", "prior_new", "temporal")},
        "document_tuning": targets, "fresh_sources": loaded["challenge_sources"], "anchor_sources": loaded["anchor_sources"],
        "fresh_document_sources": loaded["document_challenge_sources"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--temporal-manifest", type=Path, default=DEFAULT_TEMPORAL)
    args = parser.parse_args()
    print(json.dumps(freeze(args.output, args.temporal_manifest), sort_keys=True))


if __name__ == "__main__":
    main()
