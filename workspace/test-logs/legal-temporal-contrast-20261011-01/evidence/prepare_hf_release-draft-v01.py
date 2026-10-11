"""Assemble an additive experimental release from the completed guarded run."""
from pathlib import Path
import hashlib
import json
import os
import sys

F = Path(__file__).resolve().parent
REPO = "Publicus/legal-ir-autoencoder"
PREFIX = "releases/20261011-temporal-role-contrast-v1"


def pin(path):
    path = Path(path).resolve()
    assert path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def read(path):
    return json.loads(Path(path).read_bytes())


def main():
    result_root = Path(sys.argv[1]).resolve()
    summary = read(result_root / "summary.json")
    assert summary["status"] == "completed" and summary["actual_new_updates"] == 64
    assert summary["actual_encoder_calls"] == 0 and summary["default_promotion"] is False
    result_review = read(F / "result-independent-review-v01.json")
    assert result_review["passed"] is True and result_review["findings"] == []
    root = F / "hf-upload"
    root.mkdir()
    inputs = {}

    def copy(source, relative):
        before = pin(source)
        target = root / PREFIX / relative
        assert target.resolve().is_relative_to(root.resolve()) and not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(Path(source).read_bytes())
        assert pin(source) == before
        assert pin(target)["sha256"] == before["sha256"]
        inputs[relative] = before

    for path in sorted(result_root.glob("*.json")):
        copy(path, "results/" + path.name)
    for name in ("experiment-plan-v01.json", "training-export-v01.json", "authored-temporal-contrast-corpus-v01.json",
                 "inert-ambiguity-audit-v01.json", "inert-test-observation-v02.json", "corpus-independent-review-v02.json",
                 "training-protocol-independent-review-v01.json", "result-independent-review-v01.json",
                 "temporal-recovery-review-v01.json", "inert-corpus-tests-v02.xml", "inert-recipe-tests-v01.xml"):
        copy(F / name, "evidence/" + name)
    for name in ("prepare_temporal_contrast_pilot.py", "run_temporal_contrast_pilot.py", "run_scope_guardian.py"):
        copy(F / name, "recipe/" + name)
    plan = read(F / "experiment-plan-v01.json")
    for module, owner in plan["source_owner_pins"].items():
        copy(owner["path"], "source/" + module.replace(".", "/") + ".py")
    copy(F / "contribution.md", "README.md")
    manifest = dict(schema="temporal-contrast-Hub-release-manifest/v1", repository=REPO,
        prefix=PREFIX, source_inputs=inputs, actual_updates=64, arms=2, source_only=True,
        configured_dimension=384, latent_enabled=False, semantic_accuracy=None,
        independent_statutory_gold=False, default_promotion=False,
        reproducibility_scope="frozen JSON states, inputs and source; absolute historical recipe paths need explicit environment binding")
    with (root / PREFIX / "release-manifest.json").open("x") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    entries = {path.relative_to(root).as_posix(): pin(path) for path in sorted(root.rglob("*")) if path.is_file()}
    assert all(not path.is_symlink() for path in root.rglob("*"))
    baseline = read(F / "hf-before-file-identities-v01.json")
    assert not any(name.startswith(PREFIX + "/") for name in baseline["files"])
    receipt = dict(schema="temporal-contrast-Hub-preparation/v1", repository=REPO, release_prefix=PREFIX,
        expected_parent_revision=baseline["revision"], upload_root=str(root), complete_upload_files=entries,
        payload_files=len(entries), payload_bytes=sum(value["bytes"] for value in entries.values()),
        baseline_pin=pin(F / "hf-before-file-identities-v01.json"), result_review=pin(F / "result-independent-review-v01.json"),
        default_promotion=False, additive_only=True)
    with (F / "hf-preparation-receipt-v01.json").open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(dict(files=len(entries), bytes=receipt["payload_bytes"])))


if __name__ == "__main__":
    main()
