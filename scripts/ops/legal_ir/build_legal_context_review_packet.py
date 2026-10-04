#!/usr/bin/env python3
"""Build a local-only full-document source-first review packet; no model calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal import legal_context_review as review


def write(path: Path, value: dict) -> dict:
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return review.file_ref(path)


def run(manifest: str | Path, output: str | Path, *, observation_audit: str | Path | None = None,
        proposals: str | Path | None = None) -> dict:
    packet = review.build_packet(manifest, observation_audit_path=observation_audit)
    kwargs = {"expected_manifest_ref": review.file_ref(manifest),
              "expected_observation_audit_ref": review.file_ref(observation_audit) if observation_audit else None}
    validation = review.validate_packet(packet, **kwargs)
    proposal_ref = review.file_ref(proposals) if proposals else None
    proposed = review.read_ref(proposal_ref) if proposal_ref else {
        "schema": review.PROPOSAL_SCHEMA, "packet_content_sha256": review.digest(packet), "edges": []}
    proposal_validation = review.validate_attachment_proposals(packet, proposed, **kwargs)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    packet_ref = write(output / "packet.json", packet)
    validation_ref = write(output / "validation.json", validation)
    proposals_ref = write(output / "attachment-proposals.json", proposed)
    proposal_validation_ref = write(output / "attachment-validation.json", proposal_validation)
    return write(output / "summary.json", {
        "schema": "legal-document-context-review-build/v1", "source_manifest": kwargs["expected_manifest_ref"],
        "observation_audit": kwargs["expected_observation_audit_ref"], "supplied_proposals": proposal_ref,
        "packet": packet_ref, "validation": validation_ref, "attachment_proposals": proposals_ref,
        "attachment_validation": proposal_validation_ref, "counts": packet["counts"],
        "observation_counts": packet["observation_inventory"]["counts"] if packet["observation_inventory"] else None,
        "implementation": [review.file_ref(__file__), *packet["implementation"]],
        "model_inference": False, "training_executed": False, "downloads_performed": False,
        "external_reviews_received": 0, "semantic_accuracy_available": False,
        "gold_targets_created": 0, "training_qualified": False})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observation-audit", type=Path)
    parser.add_argument("--proposals", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.manifest, args.output, observation_audit=args.observation_audit,
                         proposals=args.proposals)))


if __name__ == "__main__":
    main()
