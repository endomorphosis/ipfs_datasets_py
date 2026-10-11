"""Prepare additive retained checkpoint publication after frozen replay."""
from hashlib import sha256
from pathlib import Path
import argparse
import json
import shutil

F = Path(__file__).resolve().parent


def pin(path):
    path = Path(path)
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def main(results):
    results = Path(results)
    summary = json.loads((results / "summary.json").read_bytes())
    assert summary["status"] == "completed" and summary["actual_optimizer_updates"] == 0
    assert summary["actual_encoder_calls"] == 0 and summary["all_original_artifacts_byte_exact"] is True
    destination = F / "hub-release"
    destination.mkdir()
    inventory = {}
    unique = {lane["name"]: lane["checkpoint"] for lane in summary["lanes"]}
    assert set(unique) == {"raw384-1729", "source_only-1729"}
    for name, reference in unique.items():
        assert pin(reference["path"]) == reference
        target = destination / "checkpoints" / name / "checkpoint-400.json"
        target.parent.mkdir(parents=True)
        shutil.copyfile(reference["path"], target)
        inventory[str(target.relative_to(destination))] = {"source": reference, "retained_bytes": pin(target)}
    for source in (F / "raw384-equivalence.json", F / "pointer-comparison-diagnostics.json",
                   F / "protocol-review-immutable.json", results / "summary.json"):
        assert source.exists()
        target = destination / "evidence" / source.name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
        inventory[str(target.relative_to(destination))] = {"source": pin(source), "retained_bytes": pin(target)}
    for name, path in json.loads((F / "experiment-plan.json").read_bytes())["source_owner_pins"].items():
        source = Path(path["path"])
        assert pin(source) == path
        relative = source.relative_to(F / "datasets")
        target = destination / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        inventory[str(target.relative_to(destination))] = {"source": path, "retained_bytes": pin(target)}
    readme = '''# Retained raw384 and source-only pointer decoder checkpoints

These are the unchanged selected `checkpoint-400.json` artifacts from the
October 2, 2026 native-conditioning experiment, published for preservation and
replay. This release performs zero new training updates. The source encoder is
a UTF8 byte representation plus bidirectional GRU; learned heads select O/P/F,
optional facet presence and exact token-aligned source intervals. The raw384
model conditions the source features through a bounded FiLM adapter. The
matched source-only checkpoint disables that adapter in its saved configuration.

Both artifacts retain the authoritative warm-start continuation wrapper,
embedded source parent, saved Adam moments, data manifest hashes and original
context contract. They are distinct from the normative32 recurrent decoder,
the byte259 anchored transport codec, and native-dimensional span checkpoints.
The raw input is the pinned GTE-small384 mean-pooled L2-normalized CPU float32
representation. It cannot be replaced by a same-width learned projection.
The accompanying profile audit records old/current producer hashes and the
different batch sizes without asserting identical output bits across batches.

Training targets were authored source-copy examples. The corpus has prior
exposure and does not supply independent reviewed US Code gold. The eight
October 11 real-source cases are exposed development diagnostics. Read the
comparison evidence for proposals, source warnings and abstentions; source
copying and canonical syntax are separate from correct legal roles, modality,
scope and qualifiers. No legal accuracy gain, semantic equivalence or independent
holdout result is established. No model or recipe is selected by this new assay.

The output profile contains one flat canonical deontic rule, with at most one
copied span per facet. Multiple rules, paraphrased atoms, bound variables,
multiple qualifiers, resolved document context, cognitive/event semantics and
other logic-family interpretations remain outside this decoder's scope.
No actual `lake build legal` occurs. All qualification, admission, legal meaning,
proof and default-promotion flags remain false. This is additive artifact
publication into an existing model repository, without changing defaults.

Exact source owners and evidence are retained. They require the repository's
existing Python dependencies and original environment versions; this bundle
does not claim a standalone dependency closure, a portable local-path replay or
cryptographic execution attestation. Existing source-bound cache checks still
require the externally pinned source documents and native production receipt.
'''
    (destination / "README.md").write_text(readme)
    value = {"schema": "retained-pointer-checkpoint-publication/v1", "inventory": inventory,
             "source_checkpoint_bytes_unchanged": True, "new_optimizer_updates": 0,
             "qualified": False, "admitted": False, "proof_authority": False,
             "default_promotion": False, "semantic_accuracy": None}
    (destination / "manifest.json").write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"file_count": len(list(destination.rglob("*.*"))), "checkpoints": list(unique)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True)
    main(parser.parse_args().results)
