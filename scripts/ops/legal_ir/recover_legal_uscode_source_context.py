#!/usr/bin/env python3
"""Recover immutable 2024 source context, without assigning legal meaning/gold.

The old producer's source_section_offset is a parquet row index. Exact source
occurrences here use separate, end-exclusive Python Unicode character offsets.
Multiple occurrences remain unresolved, even when a producer identifies a row.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "legal-uscode-source-context-recovery/v1"
SOURCE_REVISION = "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
SOURCE_SHA256 = "4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8"
PILOT_IDS = ("usc:us:18:4004", "usc:us:18:3284", "usc:us:10:7657",
             "usc:us:40:3318", "usc:us:10:4873")
PILOT_FEATURES = {
    "usc:us:18:4004": ["permission wording", "coordinated acts", "fee prohibition wording"],
    "usc:us:18:3284": ["deemed continuing offense", "until event", "limitations commencement"],
    "usc:us:10:7657": ["conditional permission", "recipient restriction", "reimbursement and use conditions"],
    "usc:us:40:3318": ["definitions", "duty", "discretionary exception", "nonauthorization clause"],
    "usc:us:10:4873": ["prohibition", "effective date", "waiver", "notification deadline", "practicability qualification"],
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_ref(path: Path, expected: str | None = None) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    value = {"path": str(path.absolute()), "resolved_path": str(path.resolve()),
             "bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    if expected is not None and value["sha256"] != expected:
        raise ValueError(f"input hash mismatch: {path}")
    return value


def exact_ranges(text: str, span: str) -> list[dict[str, int]]:
    """Include overlapping occurrences and never normalize the stored text."""
    if not span:
        raise ValueError("empty source span")
    ranges, cursor = [], 0
    while (start := text.find(span, cursor)) >= 0:
        end = start + len(span)
        ranges.append({"char_start": start, "char_end": end,
                       "utf8_byte_start": len(text[:start].encode("utf-8")),
                       "utf8_byte_end": len(text[:end].encode("utf-8"))})
        cursor = start + 1
    return ranges


def packet_observations(packet: dict[str, Any]) -> list[dict[str, Any]]:
    observations, seen = [], set()
    for group in packet["groups"]:
        text = group["source_text"]
        if sha256(text.encode()) != group["source_text_sha256"]:
            raise ValueError("review packet source hash mismatch")
        if group.get("gold_target") is not None or group.get("training_qualified") is not False:
            raise ValueError("expected unqualified, unreviewed packet")
        for observation in group["source_observations"]:
            sid = observation["source_span_id"]
            if sid in seen:
                raise ValueError("duplicate source observation identity")
            seen.add(sid)
            if observation.get("gold_target") is not None or observation.get("training_qualified") is not False:
                raise ValueError("unexpected qualified observation")
            reports = {}
            for occurrence in observation["occurrences"]:
                row = occurrence["producer_record"]
                if row["source_span_id"] != sid or row["source_text"] != text:
                    raise ValueError("producer occurrence differs from its source group")
                key = (row["source_report_revision"], row["source_report_path_in_repo"],
                       row["source_report_sha256"])
                reports[key] = {"repository": "justicedao/uscode-autoformal-span-cache",
                                "revision": key[0], "path_in_repo": key[1], "sha256": key[2]}
            observations.append({"source_span_id": sid, "source_text": text,
                                 "source_text_sha256": group["source_text_sha256"],
                                 "legal_ids": observation["legal_ids"],
                                 "prior_diagnostic_triage": group.get("triage", {}),
                                 "documented_span_issues": observation.get("documented_span_issues", []),
                                 "producer_reports": list(reports.values())})
    return observations


def load_cached_reports(observations: list[dict[str, Any]], cache: Path) -> tuple[dict, list]:
    reports, references = {}, {}
    for observation in observations:
        for descriptor in observation["producer_reports"]:
            key = descriptor["sha256"]
            if key in references:
                continue
            rel = Path(descriptor["path_in_repo"])
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("invalid report repository path")
            path = cache / "snapshots" / descriptor["revision"] / rel
            reference = dict(descriptor, locally_available=path.is_file())
            if path.is_file():
                reference["local_file"] = file_ref(path, key)
                payload = json.loads(gzip.decompress(path.read_bytes()))
                reports[key] = payload["rows"]
            else:
                reference["integrity_status"] = "unattested_local_report_missing"
            references[key] = reference
    return reports, list(references.values())


def producer_links(observation: dict, sections: list[dict], reports: dict) -> list[dict]:
    links = []
    for descriptor in observation["producer_reports"]:
        rows = reports.get(descriptor["sha256"])
        if rows is None:
            links.append(dict(descriptor, status="unattested_local_report_missing"))
            continue
        found = [row for row in rows if row.get("source_span_id") == observation["source_span_id"]]
        if not found:
            links.append(dict(descriptor, status="unattested_observation_missing_from_report"))
        for row in found:
            parent = row.get("source_parent", {})
            matches = [s for s in sections if s["parquet_row_index"] == row.get("source_section_offset")]
            checks = {"source_text": row.get("text") == observation["source_text"],
                      "source_sha256": row.get("source_sha256") == observation["source_text_sha256"],
                      "legal_id": row.get("legal_id") in observation["legal_ids"],
                      "parent_sha256": parent.get("sha256") == SOURCE_SHA256,
                      "parent_revision": parent.get("revision") == SOURCE_REVISION,
                      "row_index_and_cid": len(matches) == 1 and matches[0]["ipfs_cid"] == row.get("entry_cid")}
            links.append(dict(descriptor, status="producer_parent_link_verified" if all(checks.values()) else "producer_parent_link_mismatch",
                              checks=checks, parquet_row_index=row.get("source_section_offset"),
                              historical_span_ordinal=row.get("historical_span_ordinal"),
                              historical_document_batch_index=row.get("historical_document_batch_index"),
                              source_authority_authenticated=False,
                              character_occurrence_identified=False))
    return links


def recover_observation(observation: dict, sections: list[dict], reports: dict) -> dict:
    matching = [s for s in sections if s["legal_id"] in observation["legal_ids"]]
    occurrences = []
    for section in matching:
        for coords in exact_ranges(section["text"], observation["source_text"]):
            start, end = coords["char_start"], coords["char_end"]
            occurrences.append(dict(coords, parquet_row_index=section["parquet_row_index"],
                                    legal_id=section["legal_id"], raw_text_ref=section["raw_text_ref"],
                                    context_char_start=max(0, start - 240),
                                    context_char_end=min(len(section["text"]), end + 240)))
    links = producer_links(observation, matching, reports)
    mismatch = any(x["status"] == "producer_parent_link_mismatch" for x in links)
    status = "missing" if not occurrences else "unique_exact_occurrence" if len(occurrences) == 1 else "ambiguous_exact_occurrences"
    if mismatch:
        status = "producer_parent_link_mismatch"
    categories = observation["prior_diagnostic_triage"].get("categories", [])
    diagnostic = "operative_clause_candidate" if "operative_clause_candidate" in categories else "fragment_or_editorial_candidate"
    return dict(observation, producer_links=links, exact_occurrences=occurrences,
                occurrence_count=len(occurrences), source_occurrence_status=status,
                selected_occurrence=occurrences[0] if status == "unique_exact_occurrence" else None,
                source_context_integrity="exact_substring_of_pinned_parent" if occurrences and not mismatch else "unresolved",
                diagnostic_classification={"category": diagnostic, "method": "prior_lexical_triage_only",
                                           "legal_classification_confirmed": False},
                original_producer_occurrence_attested=False, source_authority_authenticated=False,
                semantic_context_verified=False, legal_meaning_reference=None,
                independent_gold=False, training_qualified=False)


def write_json(path: Path, value: Any) -> dict:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    return file_ref(path)


def run(parquet: Path, packet_path: Path, cache: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("output must be a new directory; existing artifacts are immutable")
    inputs = {"source_parquet": file_ref(parquet, SOURCE_SHA256), "review_packet": file_ref(packet_path),
              "implementation": file_ref(Path(__file__))}
    packet = json.loads(packet_path.read_text())
    observations = packet_observations(packet)
    reports, report_refs = load_cached_reports(observations, cache)
    wanted = {lid for o in observations for lid in o["legal_ids"]} | set(PILOT_IDS)
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(parquet)
    columns = ["title_number", "section_number", "ipfs_cid", "text", "jsonld_id",
               "date_modified", "source_url", "law_name"]
    sections, index = [], 0
    for batch in pf.iter_batches(batch_size=2048, columns=columns):
        for row in batch.to_pylist():
            lid = f"usc:us:{row['title_number']}:{row['section_number']}"
            if lid in wanted:
                if not isinstance(row["text"], str) or not row["text"]:
                    raise ValueError("selected parent has no complete text")
                sections.append(dict(row, legal_id=lid, parquet_row_index=index,
                                     edition="2024", source_revision=SOURCE_REVISION))
            index += 1
    if wanted - {s["legal_id"] for s in sections}:
        raise ValueError("required parent sections missing")
    output.mkdir(parents=True)
    (output / "raw-sections").mkdir()
    for section in sections:
        text = section["text"]
        path = output / "raw-sections" / f"row-{section['parquet_row_index']}-title-{section['title_number']}-section-{section['section_number']}.txt"
        with path.open("xb") as stream:
            stream.write(text.encode("utf-8"))
        section["raw_text_ref"] = file_ref(path)
        section["raw_text_characters"] = len(text)
    recovered = [recover_observation(o, sections, reports) for o in observations]
    context_refs = [{k: v for k, v in s.items() if k != "text"} for s in sections]
    context_manifest = write_json(output / "sections.json", context_refs)
    observation_ref = write_json(output / "observations.json", recovered)
    pilots = []
    for lid in PILOT_IDS:
        matches = [s for s in context_refs if s["legal_id"] == lid]
        for section in matches:
            pilots.append(dict(section, pilot_id="uscode-2024-" + lid.replace(":", "-") + f"-row-{section['parquet_row_index']}",
                               legal_id_parent_row_count=len(matches),
                               identity_contract="edition + parquet row + CID + raw-text hash + recorded heading; legal_id alone is insufficient",
                               diagnostic_features=PILOT_FEATURES[lid],
                               intended_use="source verification and independent semantic review; not training",
                               source_authority_authenticated=False, semantic_context_verified=False,
                               legal_meaning_reference=None, independent_gold=False, training_qualified=False))
    pilot_ref = write_json(output / "pilot-documents.json", pilots)
    counts = Counter(o["source_occurrence_status"] for o in recovered)
    summary = {"schema": SCHEMA, "inputs": inputs, "cached_producer_reports": report_refs,
               "source_repository": "justicedao/ipfs_uscode", "source_revision": SOURCE_REVISION,
               "source_edition": "2024", "source_parquet_rows": index,
               "source_schema": str(pf.schema_arrow),
               "counts": {"source_observations": len(recovered), "context_sections": len(sections),
                          "pilot_documents": len(pilots), "occurrence_status": dict(counts),
                          "observations_with_verified_cached_parent_link": sum(any(x["status"] == "producer_parent_link_verified" for x in o["producer_links"]) for o in recovered),
                          "exact_occurrence_candidates": sum(o["occurrence_count"] for o in recovered),
                          "independent_gold": 0, "training_qualified": 0},
               "artifacts": {"sections": context_manifest, "observations": observation_ref, "pilot_documents": pilot_ref},
               "offset_contract": {"parquet_row_index": "zero-based physical row in pinned parquet",
                                   "char_start_char_end": "zero-based end-exclusive Unicode characters in exact raw section text",
                                   "utf8_byte_start_utf8_byte_end": "zero-based end-exclusive bytes in UTF-8 raw section file"},
               "limits": ["Raw text includes operative text, headings, editorial notes, and statutory notes; no region is automatically legal gold.",
                          "Parsed subsection JSON is excluded because its hierarchy can be incorrect.",
                          "Unique exact text in the legal-id parent does not independently attest the producer's original span identity.",
                          "Repeated occurrences remain unresolved; no arbitrary occurrence is selected.",
                          "Cached producer linkage authenticates local bytes and metadata, not official authority or legal meaning.",
                          "Missing producer report files remain explicitly unattested; no network fetch was performed.",
                          "Pilot feature descriptions are diagnostic surface inventories, not formal targets.",
                          "Official-source verification, definition/cross-reference closure, independent reviews, and adjudication remain outstanding."],
               "training_executed": False, "independent_gold": False, "training_qualified": False}
    write_json(output / "audit.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", required=True, type=Path)
    parser.add_argument("--review-packet", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.parquet, args.review_packet, args.cache, args.output)
    print(json.dumps({"schema": SCHEMA, "counts": result["counts"], "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
