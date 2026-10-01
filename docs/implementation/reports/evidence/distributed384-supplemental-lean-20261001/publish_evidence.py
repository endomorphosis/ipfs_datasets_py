"""Append-only publication of supplemental Lean development evidence."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_set(directory, prefix):
    return {prefix + "/" + str(path.relative_to(directory)): path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}


def bounded_snapshot(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("existing staged evidence differs: " + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


p = argparse.ArgumentParser()
p.add_argument("--root", type=Path, required=True)
p.add_argument("--previous", type=Path, required=True)
p.add_argument("--code-commit", required=True)
p.add_argument("--upload", action="store_true")
a = p.parse_args()
if len(a.code_commit) != 40 or any(c not in "0123456789abcdef" for c in a.code_commit):
    raise ValueError("immutable Git source commit required")
api = HfApi()
records = json.loads((a.root / "checkpoints-run-01/results.json").read_text())
if any(records[k] is not False for k in (
        "training_executed", "weights_changed", "new_holdout_evaluation", "context_inferred_by_model")):
    raise ValueError("unexpected evidence scope")
publications = []
for domain in ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir"):
    old = json.loads((a.previous / domain / "merged-result.json").read_text())
    plan = json.loads((a.previous / domain / "coordinator/plan.json").read_text())
    directory = a.root / "checkpoints-run-01" / domain
    summary = json.loads((directory / "checks/summary.json").read_text())
    if summary["all_requested_native_checks_passed"] is not True or summary["target_access"] is not False:
        raise ValueError("candidate syntax replay failed or accessed targets")
    if any(summary[k] is not False for k in (
            "qualified", "admitted", "proof_authority", "source_semantics_verified", "promotion_performed")):
        raise ValueError("unexpected authority in development evidence")
    checkpoint_bytes = Path(old["checkpoint_path"]).read_bytes()
    if sha(checkpoint_bytes) != summary["checkpoint"]["sha256"]:
        raise ValueError("checkpoint differs from replayed bytes")
    result = next(row for row in records["records"] if row["domain_id"] == domain)
    files = file_set(directory, "checkpoint-prediction")
    files["run_checkpoint_checks.py"] = (a.root / "run_checkpoint_checks.py").read_bytes()
    files["result.json"] = raw(result)
    files["published-checkpoint-reference.json"] = raw(old["publication"])
    if domain == "security_ir":
        files["authored-native-evidence.tar.gz"] = (a.root / "authored-native-evidence.tar.gz").read_bytes()
        files["authored-summary.json"] = (a.root / "authored/run-01/summary.json").read_bytes()
    manifest = dict(
        schema="distributed384-supplemental-native-development-evidence/v1", domain_id=domain,
        plan_id=plan["plan_id"], checkpoint=summary["checkpoint"], published_checkpoint=old["publication"],
        code_repository="https://github.com/endomorphosis/ipfs_datasets_py", code_commit=a.code_commit,
        candidate_gate_schema="distributed-384-candidate-native-lake/v2",
        scope="one actual tuning prediction with explicitly authored context; Security also has separate original-context and authored-fragment controls",
        source_provenance="published authored source_reconstruction_v3 controls and repository-owned native fixtures",
        formulas_and_supplemental_models_are_caller_declarations=True,
        context_inferred_by_model=False, training_executed=False, weights_changed=False,
        model_source_semantic_fidelity_verified=False, new_holdout_evaluation=False,
        all_requested_dependencies_supported=summary["all_requested_dependencies_supported"],
        all_requested_native_checks_passed=summary["all_requested_native_checks_passed"],
        result=result, qualified=False, admitted=False, proof_authority=False,
        promotion_performed=False, source_semantics_verified=False,
        files=[dict(path=name, sha256=sha(data), bytes=len(data)) for name, data in sorted(files.items())])
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name, data in sorted(files.items()):
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                entry.mode = 0o644
                entry.mtime = 0
                tar.addfile(entry, io.BytesIO(data))
    bundle = compressed.getvalue()
    manifest["archive"] = dict(path="evidence.tar.gz", sha256=sha(bundle), bytes=len(bundle))
    manifest_bytes = raw(manifest)
    identity = sha(manifest_bytes)
    prefix = "training/structured384/" + plan["plan_id"] + "/projection-checks/" + identity
    stage = a.root / "publication" / domain
    for filename, data in (("manifest.json", manifest_bytes), ("evidence.tar.gz", bundle)):
        bounded_snapshot(stage / filename, data)
    repo = old["publication"]["repository_id"]
    receipt = dict(repository_id=repo, repo_type="model", path=prefix, manifest_sha256=identity,
                   archive_sha256=sha(bundle), archive_bytes=len(bundle), uploaded=False)
    if a.upload:
        info = api.model_info(repo)
        existing = {x.rfilename for x in info.siblings}
        desired = {prefix + "/manifest.json": manifest_bytes, prefix + "/evidence.tar.gz": bundle}
        if set(desired) & existing:
            if not set(desired) <= existing:
                raise ValueError("partial publication requires investigation")
            revision = info.sha
        else:
            commit = api.create_commit(repo_id=repo, repo_type="model", parent_commit=info.sha,
                operations=[CommitOperationAdd(path_in_repo=name, path_or_fileobj=io.BytesIO(data))
                            for name, data in desired.items()],
                commit_message="Archive scoped supplemental native Lean development checks")
            revision = commit.oid
        for name, data in desired.items():
            fetched = Path(hf_hub_download(repo_id=repo, repo_type="model", filename=name, revision=revision))
            if sha(fetched.read_bytes()) != sha(data):
                raise ValueError("published artifact verification failed")
        receipt.update(uploaded=True, revision=revision, download_verified=True,
            url="https://huggingface.co/" + repo + "/blob/" + revision + "/" + prefix + "/manifest.json")
    (stage / "receipt.json").write_bytes(raw(receipt))
    publications.append(receipt)
    print(json.dumps(receipt), flush=True)
(a.root / "publication/receipts.json").write_bytes(raw(publications))
