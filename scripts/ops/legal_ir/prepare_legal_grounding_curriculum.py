#!/usr/bin/env python3
"""Freeze a coordinate-supervised, authored deontic grounding curriculum.

The annotations express this generator's stipulated semantics, not reviewed law.
Training readers never open the separately stored challenge annotations. Source
coordinates are recorded while rendering, including repeated surface strings.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "legal-grounding-curriculum/v1"
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
ROW_KEYS = {"id", "source_text", "canonical_ir", "trigger_span", "facet_spans"}
SPLITS = ("train", "tuning", "challenge")
MODALS = (
    {"O": "shall", "P": "may", "F": "shall not"},
    {"O": "must", "P": "is allowed to", "F": "must not"},
    {"O": "has a duty to", "P": "has permission to", "F": "is forbidden to"},
    {"O": "is required to", "P": "is permitted to", "F": "is not permitted to"},
)
TRIGGER_MEANINGS = {phrase: modality for modal in MODALS for modality, phrase in modal.items()}
NAMES = {
    "train": ("Wexford", "Bellhaven", "Dunwick", "Fenbridge", "Glenhurst", "Harrowden", "Iverton", "Kingswell", "Lowmere", "Mereford", "Northwick", "Oakmere", "Penwick", "Ravensby", "Southmere", "Thornby", "Uptonwell", "Westmere", "Yewbridge", "Zennor"),
    "tuning": ("Ashcombe", "Briarmere", "Corwick", "Dalehurst", "Eastwyke", "Foxwell", "Greyford", "Highmere"),
    "challenge": ("Ivydale", "Kirkhurst", "Longwyke", "Mossbridge", "Netherford", "Orwellby", "Pinewick", "Queensmere", "Rookhaven", "Stonewyke"),
}
ACTOR_FORMS = (
    "{name}", "{name} Registry", "{name} May Office", "{name} Permission Review Bureau",
    "{name} Office of Public Records", "{name} Board for Required Record Review",
    "{name} Office for May and Must Notices", "{name} Department for Permission and Mandatory Records Review",
)
CONSTRUCTIONS = {
    "train": ("suffix_qualifiers", "citation_prefix", "condition_prefix", "exception_prefix", "actor_citation_insertion"),
    "tuning": ("temporal_prefix", "condition_exception_prefix", "postmodal_citation", "citation_condition_prefix"),
    "challenge": ("exception_condition_prefix", "temporal_exception_prefix", "actor_condition_insertion", "semicolon_rule_scope", "citation_temporal_prefix"),
}
CASES_PER_CONSTRUCTION = {"train": 40, "tuning": 8, "challenge": 10}
CONSTRUCTION_DESCRIPTIONS = {
    "suffix_qualifiers": "A M V X [if C] [unless E] [T].",
    "citation_prefix": "Under citation, A M V X [T] [if C] [unless E].",
    "condition_prefix": "If C, A M V X [unless E] [T].",
    "exception_prefix": "Unless E, A M V X [if C] [T].",
    "actor_citation_insertion": "A, under citation, M V X [if C] [unless E] [T].",
    "temporal_prefix": "T, A M V X [unless E] [if C].",
    "condition_exception_prefix": "If C, unless E, A M V X [T].",
    "postmodal_citation": "A M, under citation, V X [unless E] [if C] [T].",
    "citation_condition_prefix": "Under citation, if C, A M V X [T] [unless E].",
    "exception_condition_prefix": "Unless E, if C, A M V X [T].",
    "temporal_exception_prefix": "T, unless E, A M V X [if C].",
    "actor_condition_insertion": "A, if C, M V X [unless E] [T].",
    "semicolon_rule_scope": "A M V X; this rule applies if C [unless E] [T].",
    "citation_temporal_prefix": "Pursuant to citation, T, A M V X [unless E] [if C].",
}
ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT.parents[1] / "artifacts"
DEFAULT_HISTORICAL = ARTIFACTS / "legal-decoder-native-conditioning-20261002/prepared/corpus.json"


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": sha(raw), "bytes": len(raw)}


def verify_ref(ref):
    if set(ref) != {"path", "sha256", "bytes"}:
        raise ValueError("closed artifact reference required")
    raw = Path(ref["path"]).read_bytes()
    if len(raw) != ref["bytes"] or sha(raw) != ref["sha256"]:
        raise ValueError("artifact hash or size differs")
    return raw


def read_ref(ref):
    return json.loads(verify_ref(ref))


def write_new(path, value):
    raw = canonical_bytes(value)
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return file_ref(path)


class CoordinateWriter:
    def __init__(self):
        self.text = ""
        self.spans = {}

    def add(self, text, field=None):
        start = len(self.text)
        self.text += text
        if field is not None:
            if field in self.spans or not text:
                raise ValueError("one nonempty occurrence per role required")
            self.spans[field] = [start, len(self.text)]


def render_row(split, construction, index, modality):
    """Render one occurrence using coordinates, never substring search."""
    if construction not in CONSTRUCTIONS[split] or modality not in {"O", "P", "F"}:
        raise ValueError("unknown construction or modality")
    name = NAMES[split][index % len(NAMES[split])]
    actor = ACTOR_FORMS[index % len(ACTOR_FORMS)].format(name=name)
    values = {
        "actor": actor,
        "action": ("inspect", "retain", "submit", "archive", "review", "publish")[index % 6],
        "object": f"the {name.lower()} register number {index + 101}",
        "conditions": (f"{actor} receives the permit" if index % 4 == 0 else f"the {name.lower()} permit is active"),
        "exceptions": (f"{actor} receives an exemption" if index % 5 == 0 else f"the {name.lower()} exemption is active"),
        "temporal": f"within {index + 17} days",
    }
    present = {field for bit, field in enumerate(FIELDS[3:]) if index & (1 << bit)}
    required = {
        "condition_prefix": {"conditions"}, "exception_prefix": {"exceptions"},
        "temporal_prefix": {"temporal"}, "condition_exception_prefix": {"conditions", "exceptions"},
        "citation_condition_prefix": {"conditions"}, "exception_condition_prefix": {"conditions", "exceptions"},
        "temporal_exception_prefix": {"temporal", "exceptions"}, "actor_condition_insertion": {"conditions"},
        "semicolon_rule_scope": {"conditions"}, "citation_temporal_prefix": {"temporal"},
    }
    present.update(required.get(construction, set()))
    remaining = set(present)
    writer = CoordinateWriter()

    def role(field):
        writer.add(values[field], field)
        remaining.discard(field)

    def qualifier(field, prefix, suffix):
        writer.add(prefix)
        role(field)
        writer.add(suffix)

    citation = f"section {811 + index}(c)"
    if construction == "citation_prefix":
        writer.add(f"Under {citation}, ")
    elif construction == "condition_prefix":
        qualifier("conditions", "If ", ", ")
    elif construction == "exception_prefix":
        qualifier("exceptions", "Unless ", ", ")
    elif construction == "temporal_prefix":
        qualifier("temporal", "", ", ")
    elif construction == "condition_exception_prefix":
        qualifier("conditions", "If ", ", ")
        qualifier("exceptions", "unless ", ", ")
    elif construction == "citation_condition_prefix":
        writer.add(f"Under {citation}, ")
        qualifier("conditions", "if ", ", ")
    elif construction == "exception_condition_prefix":
        qualifier("exceptions", "Unless ", ", ")
        qualifier("conditions", "if ", ", ")
    elif construction == "temporal_exception_prefix":
        qualifier("temporal", "", ", ")
        qualifier("exceptions", "unless ", ", ")
    elif construction == "citation_temporal_prefix":
        writer.add(f"Pursuant to {citation}, ")
        qualifier("temporal", "", ", ")
    role("actor")
    if construction == "actor_citation_insertion":
        writer.add(f", under {citation}, ")
    elif construction == "actor_condition_insertion":
        qualifier("conditions", ", if ", ", ")
    else:
        writer.add(" ")
    modal_index = (index // len(ACTOR_FORMS) + CONSTRUCTIONS[split].index(construction)) % len(MODALS)
    writer.add(MODALS[modal_index][modality], "trigger")
    writer.add(f", under {citation}, " if construction == "postmodal_citation" else " ")
    role("action")
    writer.add(" ")
    role("object")
    if construction == "semicolon_rule_scope":
        qualifier("conditions", "; this rule applies if ", "")
    order = {
        "citation_prefix": ("temporal", "conditions", "exceptions"),
        "temporal_prefix": ("exceptions", "conditions", "temporal"),
        "postmodal_citation": ("exceptions", "conditions", "temporal"),
        "citation_condition_prefix": ("temporal", "exceptions", "conditions"),
        "citation_temporal_prefix": ("exceptions", "conditions", "temporal"),
    }.get(construction, FIELDS[3:])
    for field in order:
        if field in remaining:
            qualifier(field, {"conditions": " if ", "exceptions": " unless ", "temporal": " "}[field], "")
    writer.add(".")
    rule = {"modality": modality, **{field: values[field] for field in FIELDS[:3]},
            **{field: [values[field]] if field in present else [] for field in FIELDS[3:]}}
    row = {"id": f"grounding-{split}-{sha(writer.text.encode())[:20]}", "source_text": writer.text,
           "canonical_ir": {"rules": [rule]}, "trigger_span": writer.spans["trigger"],
           "facet_spans": {field: writer.spans.get(field) for field in FIELDS}}
    validate_row(row)
    return row


def validate_row(row):
    if set(row) != ROW_KEYS or not isinstance(row["id"], str) or not row["id"]:
        raise ValueError("closed coordinate-supervision row required")
    text = row["source_text"]
    if not isinstance(text, str) or not text:
        raise ValueError("nonempty source required")
    ir = row["canonical_ir"]
    if set(ir) != {"rules"} or not isinstance(ir["rules"], list) or len(ir["rules"]) != 1:
        raise ValueError("exactly one rule required")
    rule = ir["rules"][0]
    if set(rule) != {"modality", *FIELDS} or rule["modality"] not in {"O", "P", "F"}:
        raise ValueError("closed deontic rule required")
    if set(row["facet_spans"]) != set(FIELDS):
        raise ValueError("complete facet coordinate map required")
    tokens = list(re.finditer(r"\w+|[^\w\s]", text, flags=re.UNICODE))
    starts, ends = {m.start() for m in tokens}, {m.end() for m in tokens}
    occupied = []

    def check_span(span):
        if (not isinstance(span, list) or len(span) != 2 or any(type(v) is not int for v in span)
                or not (0 <= span[0] < span[1] <= len(text)) or span[0] not in starts or span[1] not in ends):
            raise ValueError("half-open token-aligned coordinates required")
        if any(span[0] < b and a < span[1] for a, b in occupied):
            raise ValueError("role and trigger spans overlap")
        occupied.append(span)
        return text[span[0]:span[1]]

    if TRIGGER_MEANINGS.get(check_span(row["trigger_span"])) != rule["modality"]:
        raise ValueError("trigger does not bind stipulated modality")
    for field in FIELDS:
        value, span = rule[field], row["facet_spans"][field]
        if field in FIELDS[:3]:
            if not isinstance(value, str) or not value or span is None or check_span(span) != value:
                raise ValueError("required facet differs from source coordinates")
        elif value == [] and span is None:
            continue
        elif not isinstance(value, list) or len(value) != 1 or span is None or check_span(span) != value[0]:
            raise ValueError("optional facet differs from source coordinates")
    return row


def normalized_source(text):
    return " ".join(re.findall(r"\w+|[^\w\s]", text.casefold()))


def make_panels():
    panels, construction_membership = {}, {}
    for split in SPLITS:
        rows, membership = [], {}
        for construction in CONSTRUCTIONS[split]:
            for index in range(CASES_PER_CONSTRUCTION[split]):
                for modality in ("O", "P", "F"):
                    row = render_row(split, construction, index, modality)
                    rows.append(row)
                    membership[row["id"]] = construction
        # Deterministic source-hash order does not expose a periodic modality label.
        panels[split] = sorted(rows, key=lambda row: sha(row["source_text"].encode()))
        construction_membership[split] = membership
    check_panels(panels, construction_membership)
    return panels, construction_membership


def check_panels(panels, membership):
    seen_ids, seen_sources, seen_normalized, seen_targets = set(), {}, {}, {}
    for split in SPLITS:
        rows = panels[split]
        if len(rows) != len(CONSTRUCTIONS[split]) * CASES_PER_CONSTRUCTION[split] * 3:
            raise ValueError("unexpected panel size")
        if set(membership[split]) != {row["id"] for row in rows}:
            raise ValueError("construction membership differs")
        counts = Counter()
        for row in rows:
            validate_row(row)
            if row["id"] in seen_ids:
                raise ValueError("duplicate row id")
            seen_ids.add(row["id"])
            for key, table in ((sha(row["source_text"].encode()), seen_sources),
                               (normalized_source(row["source_text"]), seen_normalized),
                               (sha(canonical_bytes(row["canonical_ir"])), seen_targets)):
                if key in table and table[key] != split:
                    raise ValueError("source or full target overlaps splits")
                if table is not seen_targets and key in table:
                    raise ValueError("duplicate source within split")
                table[key] = split
            construction = membership[split][row["id"]]
            if construction not in CONSTRUCTIONS[split]:
                raise ValueError("construction crosses split")
            counts[(construction, row["canonical_ir"]["rules"][0]["modality"])] += 1
        if any(counts[(c, m)] != CASES_PER_CONSTRUCTION[split] for c in CONSTRUCTIONS[split] for m in ("O", "P", "F")):
            raise ValueError("unbalanced modality construction panel")
    if any(set(CONSTRUCTIONS[a]) & set(CONSTRUCTIONS[b]) for a, b in (("train", "tuning"), ("train", "challenge"), ("tuning", "challenge"))):
        raise ValueError("surface constructions overlap")


def extract_sources(value):
    if isinstance(value, dict):
        if isinstance(value.get("source_text"), str):
            yield value["source_text"]
        for child in value.values():
            yield from extract_sources(child)
    elif isinstance(value, list):
        for child in value:
            yield from extract_sources(child)


def freeze(output, historical_paths):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    panels, membership = make_panels()
    new_sources = {sha(row["source_text"].encode()) for rows in panels.values() for row in rows}
    new_normalized = {normalized_source(row["source_text"]) for rows in panels.values() for row in rows}
    historical_refs, historical_sources = [], set()
    for path in historical_paths:
        ref = file_ref(path)
        sources = set(extract_sources(read_ref(ref)))
        if not sources:
            raise ValueError("historical corpus contains no source_text records")
        if new_sources & {sha(s.encode()) for s in sources} or new_normalized & {normalized_source(s) for s in sources}:
            raise ValueError("new curriculum overlaps historical source corpus")
        historical_sources.update(sources)
        historical_refs.append({"artifact": ref, "unique_sources": len(sources)})
    if not historical_refs:
        raise ValueError("at least one historical corpus audit is required")
    artifacts = {
        "train": write_new(output / "train.json", panels["train"]),
        "tuning": write_new(output / "tuning.json", panels["tuning"]),
        "challenge_sources": write_new(output / "challenge-sources.json", [{"id": r["id"], "source_text": r["source_text"]} for r in panels["challenge"]]),
        "challenge_targets": write_new(output / "challenge-targets.sealed.json", panels["challenge"]),
        "construction_membership": write_new(output / "construction-membership.sealed.json", membership),
    }
    summaries = {}
    for split, rows in panels.items():
        rules = [r["canonical_ir"]["rules"][0] for r in rows]
        summaries[split] = {"count": len(rows), "construction_ids": list(CONSTRUCTIONS[split]),
            "modalities": dict(Counter(r["modality"] for r in rules)),
            "qualifier_counts": dict(sorted(Counter(str(sum(bool(r[f]) for f in FIELDS[3:])) for r in rules).items())),
            "actor_word_counts": dict(sorted(Counter(str(len(r["actor"].split())) for r in rules).items())),
            "repeated_actor_surface_rows": sum(row["source_text"].count(rule["actor"]) > 1 for row, rule in zip(rows, rules)),
            "source_sha256s": [sha(r["source_text"].encode()) for r in rows]}
    manifest = {"schema": SCHEMA, "provenance": "authored_synthetic_not_legal_authority", "qualified": False,
        "independently_reviewed": False, "frozen_before_fitting": True, "artifacts": artifacts, "splits": summaries,
        "challenge_count": len(panels["challenge"]), "generator": file_ref(__file__),
        "construction_descriptions": CONSTRUCTION_DESCRIPTIONS,
        "semantics": {"trigger_meanings": TRIGGER_MEANINGS, "O": "obligation", "P": "permission", "F": "prohibition",
            "condition": "if/when clause is a positive applicability antecedent",
            "exception": "unless clause defeats applicability while true",
            "temporal": "within N days is a rule deadline relative to an externally supplied activation anchor",
            "one_rule": "All qualifiers in these authored sentences attach to the sole rule, including the explicit semicolon rule-scope clause.",
            "not_permitted": "is not permitted to is stipulated to denote prohibition, not merely absence of a permission proof",
            "excluded": ["may not", "nested negation", "shared or nested scope", "cross references requiring interpretation", "multiple rules", "unreviewed statutory gold"]},
        "historical_overlap_audit": {"inputs": historical_refs, "unique_historical_sources": len(historical_sources), "exact_overlaps": 0, "normalized_overlaps": 0,
            "scope": "Compared the explicitly pinned historical corpus source_text records; not a global filesystem or internet uniqueness claim."},
        "limitations": ["Constructed gold under stipulated semantics; no independent legal review.", "Construction families are held out, but words and modal paraphrases intentionally overlap.", "File separation prevents accidental target reads; it is not access-control encryption.", "Prior five observed errors are excluded from this new evaluation and remain exposed regression evidence."]}
    return write_new(output / "manifest.json", manifest)


def load_training_inputs(manifest_path):
    """Return manifest, annotated train/tuning, and SOURCE-ONLY challenge rows.

    Deliberately never opens challenge_targets or construction_membership.
    A fitting runner must freeze predictions before separately opening targets.
    """
    manifest = json.loads(Path(manifest_path).read_bytes())
    if manifest.get("schema") != SCHEMA or not manifest.get("frozen_before_fitting"):
        raise ValueError("frozen grounding manifest required")
    verify_ref(manifest["generator"])
    train = read_ref(manifest["artifacts"]["train"])
    tuning = read_ref(manifest["artifacts"]["tuning"])
    challenge = read_ref(manifest["artifacts"]["challenge_sources"])
    seen_ids, seen_sources = set(), set()
    for split, rows in (("train", train), ("tuning", tuning), ("challenge", challenge)):
        if len(rows) != manifest["splits"][split]["count"]:
            raise ValueError("split count differs")
        if [sha(r["source_text"].encode()) for r in rows] != manifest["splits"][split]["source_sha256s"]:
            raise ValueError("source membership differs")
        for row in rows:
            if split == "challenge":
                if set(row) != {"id", "source_text"}:
                    raise ValueError("challenge must be source-only")
            else:
                validate_row(row)
            source_key = normalized_source(row["source_text"])
            if row["id"] in seen_ids or source_key in seen_sources:
                raise ValueError("duplicate id or source across admitted inputs")
            seen_ids.add(row["id"])
            seen_sources.add(source_key)
    return manifest, train, tuning, challenge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--historical-corpus", type=Path, action="append")
    args = parser.parse_args()
    print(json.dumps(freeze(args.output, args.historical_corpus or [DEFAULT_HISTORICAL]), sort_keys=True))


if __name__ == "__main__":
    main()
