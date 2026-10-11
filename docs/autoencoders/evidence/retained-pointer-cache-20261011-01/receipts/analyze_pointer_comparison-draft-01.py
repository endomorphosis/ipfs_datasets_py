"""Pure, source-only coverage comparison; no target or model replay."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import argparse
import json


def read(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= 8 * 1024**2
    return json.loads(path.read_bytes())


def pin(path):
    path = Path(path)
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def analyze(root, previous, output):
    root, previous = Path(root), Path(previous)
    summary = read(root / "summary.json")
    reports = []
    # Each lane preserves its authoritative continuation report inside the
    # cache adapter receipt. The explicit source join precedes this diagnostic.
    for lane in summary["lanes"]:
        path = Path(lane["report"]["path"])
        assert pin(path) == lane["report"]
        report = read(path)
        copied, proposals, abstentions = Counter(), 0, Counter()
        observations = []
        for row in report["rows"]:
            raw = row.get("decoder_row")
            item = {"id": row["id"], "outcome": row["outcome"],
                    "source_sha256": row["source_sha256"]}
            if raw is None:
                abstentions[row["outcome"]] += 1
            elif raw["status"] != "decoded":
                abstentions[raw["reason"]] += 1
                item["reason"] = raw["reason"]
            else:
                proposals += 1
                rule = raw["canonical_ir"]["rules"][0]
                facets = raw["span_diagnostics"]["facets"]
                item["canonical_ir"] = raw["canonical_ir"]
                item["facet_intervals"] = {}
                for facet, diagnostic in facets.items():
                    if diagnostic["present"]:
                        item["facet_intervals"][facet] = {
                            key: diagnostic[key] for key in ("char_start", "char_end", "text")}
                        copied[facet] += 1
                item["modality"] = rule["modality"]
            observations.append(item)
        reports.append({"name": lane["name"], "control": lane["control"],
            "checkpoint": lane["checkpoint"], "report": pin(path),
            "source_count": len(report["rows"]), "decoded_proposals": proposals,
            "abstention_reasons": dict(abstentions), "nonempty_source_copied_facets": dict(copied),
            "rows": observations, "semantic_accuracy": None,
            "legal_roles_verified": False, "modality_semantics_verified": False})
    baseline = read(previous)
    result = {"schema": "retained-pointer-source-coverage-comparison/v1",
        "current_summary": pin(root / "summary.json"), "previous_normative_diagnostics": pin(previous),
        "lanes": reports, "all_sources_exposed_development_cases": True,
        "independent_holdout": False, "reference_targets_accessed": False,
        "actual_optimizer_updates": 0, "source_copying_is_semantic_accuracy": False,
        "source_semantics_verified": False, "logic_family_admission": False,
        "Lake_executed": False, "proof_authority": False,
        "previous_schema": baseline.get("schema"),
        "measurement_scope": "Literal nonempty copied facets and refusals; no legal gold or accuracy ranking."}
    with Path(output).open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"lanes": [{k: lane[k] for k in ("name", "control", "decoded_proposals",
        "abstention_reasons", "nonempty_source_copied_facets")} for lane in reports]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    analyze(args.run, args.previous, args.output)
