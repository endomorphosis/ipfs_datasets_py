"""Prepare repository evidence from finalized owned files; excludes weights/ledgers."""
from hashlib import sha256
from pathlib import Path
import json
import shutil
import sys
import argparse

F = Path(__file__).resolve().parent
D, W = F / "datasets", F / "workspace"


def pin(path):
    path = Path(path)
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def main(run, input_inventory):
    run = Path(run)
    read_paths = [run / "results/summary.json", F / "pointer-comparison-diagnostics.json",
                  F / "hub-publication-receipt.json", Path(input_inventory)]
    consumed = {str(path): pin(path) for path in read_paths}
    summary = json.loads((run / "results/summary.json").read_bytes())
    assert summary["status"] == "completed"
    diagnostics = json.loads((F / "pointer-comparison-diagnostics.json").read_bytes())
    hub = json.loads((F / "hub-publication-receipt.json").read_bytes())
    assert hub["all_new_file_downloads_byte_verified"] is True and hub["prior_file_identities_preserved"] is True
    selected_inputs = json.loads(Path(input_inventory).read_bytes())
    assert all(pin(path) == reference for path, reference in consumed.items())
    assert selected_inputs["schema"] == "retained-pointer-contribution-inputs/v1"
    assert 1 <= len(selected_inputs["entries"]) <= 256
    evidence = D / "docs/autoencoders/evidence/retained-pointer-cache-20261011-01"
    evidence.mkdir(parents=True)
    inventory = {}

    def retain(source, relative, expected):
        source = Path(source)
        assert source.is_file() and not source.is_symlink() and source.stat().st_size <= 2 * 1024**2
        before = pin(source)
        assert before == expected
        if str(source) in consumed:
            assert before == consumed[str(source)]
        assert not relative.is_absolute() and ".." not in relative.parts
        target = evidence / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        retained = pin(target)
        assert {key: retained[key] for key in ("bytes", "sha256")} == {key: before[key] for key in ("bytes", "sha256")}
        assert pin(source) == before
        consumed[str(source)] = before
        inventory[str(relative)] = {"origin": before, "retained": retained}
    for entry in selected_inputs["entries"]:
        assert set(entry) == {"pin", "relative", "role"}
        source = Path(entry["pin"]["path"])
        assert entry["role"] in {"owned_receipt", "owned_attempt", "raw_source_view", "previous_pilot_receipt"}
        assert not any(value in source.name for value in ("selected-state", "checkpoint-", "disk-reservations", "resource-before-", "resource-after-", "hub-before-publication"))
        retain(source, Path(entry["relative"]), entry["pin"])
    declared = {entry["pin"]["path"]: entry["pin"] for entry in selected_inputs["entries"]}
    assert all(declared[str(path)] == consumed[str(path)] for path in read_paths[:3])
    retain(Path(input_inventory), Path("receipts") / Path(input_inventory).name,
           consumed[str(Path(input_inventory))])
    assert all(pin(path) == reference for path, reference in consumed.items())
    # Hub publication stores checkpoint bytes separately; source evidence keeps
    # only release metadata and immutable verification receipts.
    value = {"schema": "retained-pointer-cache-evidence-manifest/v1", "files": inventory,
             "weights_in_source_evidence": False, "full_shared_ledgers_in_evidence": False,
             "source_count": 8, "optimizer_updates": 0, "encoder_calls": 0,
             "semantic_accuracy": None, "Lake_executed": False,
             "qualification": False, "scope": "Frozen replay, source-copy diagnostics and exact artifact custody.",
             "copy_inputs": pin(input_inventory), "closing_source_bytes_unchanged": True}
    (evidence / "manifest.json").write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    rows = []
    for lane in diagnostics["lanes"]:
        rows.append(f"|{lane['name']}|{lane['control']}|{lane['eligible_count']}/8|{lane['decoded_proposals']}/8|{json.dumps(lane['abstention_reasons'], sort_keys=True)}|")
    document = '''# Retained open-vocabulary pointer decoder on new native-cache sources

The opt-in `arbitrary_native_span_runtime` connects the new source-bound raw
GTE384 cache to the existing warm-start source-span decoder. It preserves the
continuation lineage and restores the selected October 2 raw384/source-only
checkpoints; it creates no new neural architecture or checkpoint. Pure
preparation verifies source occurrences, raw-vector receipts, a pinned historical
recipe compatibility audit and current source owners before numerical opening.
Raw vectors cannot be passed off as `core384` or `trained384` projections.

The same eight exposed US Code spans from the previous native-cache pilot run
through both retained checkpoints under none, zero, disabled and rotate controls.
Rotation uses the original occurrence order before source preflight filtering.
Source warnings, missing eligibility, abstentions and candidate facet intervals
remain explicit. The cached paragraph vector is used; clause vectors and full
document context are not model inputs. This run performs zero encoder calls,
zero optimizer updates and no checkpoint or recipe selection.

| Retained checkpoint | Control | Eligible | Copied proposals | Other dispositions |
| --- | --- | ---: | ---: | --- |
''' + "\n".join(rows) + '''

Every emitted nonempty facet is copied from an exact source interval and checked
against the retained canonical single-rule grammar. These are source-grounding
and syntax observations, not correct legal roles or semantic accuracy. The
previous normative32 lanes each generated eight canonical candidates but had
case-sensitive actor/action/object literal counts0/1/0 out of8. Those counts are
substring diagnostics, while this pointer assay checks exact model-selected
intervals; neither is independently reviewed legal gold. Refusals stay in the
denominator and absent object/qualifier fields are not counted as copied values.

The public `justicedao/open-us-law-span-cache` snapshot3bdc4d5 exposes51 jurisdiction
inventory rows, without source text, IR, embeddings or review labels. Its storage
split name does not admit training. The accompanying eight-row real-law review
packet binds raw physical spans and complete section artifacts, leaves semantic
targets unassigned and keeps all supervision/evaluation masks0. It is a distinct
context-aware template: the existing authored v1 review recorder requires empty
context and cannot consume this packet as a reviewed legal corpus.

The decoder can represent one flat O/P/F rule with one exact copied span per
facet. It cannot express definitions, multiple rules, paraphrases, multiple
values within a qualifier facet or variable binding. A future training cohort must first receive
independent source-context review and an explicit representability disposition.
Keep weak/generated labels separate from reviewed targets and keep the eight
development spans outside any claimed independent confirmation split. Evaluate
facet roles, modality, qualifier preservation, contradictions and calibrated
abstention before selecting a new checkpoint. Reuse these pointer heads with
the structural decoder's grammar constraints only under a distinct audited
readout/training lineage; never repair a failed output and score it as raw output.

The frozen guardian retains its original2CPU/1536MiB/onechild/200MB/300second
envelope. Sampled process-group RSS is a cooperative observation rather than a
kernel quota or absolute peak. Exact protocol review bytes are retained under a
versioned immutable filename and checked against pre-admission evidence. The
old native-cache review-byte custody gap remains historical and is not repaired
or inherited as a clean claim here. Source, checkpoint and canonical checkout
custody are audited separately.

The source-only/correct/zero/disabled/rotated comparison does not qualify the
broader logic families. It supplies copied facets that still require caller
interpretation and supported source-family lowering. No `lake build legal`
occurs, no legal meaning or proof is verified, and no default is promoted.

[Exact bounded evidence](evidence/retained-pointer-cache-20261011-01/manifest.json)
retains the raw outputs, source views, resource receipts, review templates,
protocol review, tests and preserved drafts. Raw checkpoints are retained on
the model Hub; full shared ledger snapshots stay local.
'''
    doc = D / "docs/autoencoders/retained_pointer_cache_20261011.md"
    doc.write_text(document)
    mirror = W / "artifacts/legal-open-vocabulary-20261011-01"
    shutil.copytree(evidence, mirror / "evidence")
    target = W / "implementation_plan/docs/73-retained-pointer-source-cache-2026-10-11.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document.replace("evidence/retained-pointer-cache-20261011-01/manifest.json",
        "../../artifacts/legal-open-vocabulary-20261011-01/evidence/manifest.json"))
    print(json.dumps({"source_evidence_files": len(inventory), "source_document": str(doc),
                      "workspace_document": str(target)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--inventory", required=True)
    args = parser.parse_args()
    main(args.run, args.inventory)
