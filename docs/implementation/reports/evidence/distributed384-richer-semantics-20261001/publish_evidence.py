"""Append-only publication of explicitly interpreted native development evidence.

Validation is offline. Staging requires an immutable tested code commit; uploading
requires --upload. No weights, training-target rows, holdout rows, model cards, or defaults are
uploaded. Successful native compilation can contain a proved counterexample.
"""
import argparse
from copy import deepcopy
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir")
REPOSITORIES = {
    "intent_ir": "Publicus/intent-ir-autoencoder",
    "security_ir": "Publicus/security-ir-autoencoder",
    "ui_ux_ir": "Publicus/ui-ux-ir-autoencoder",
    "legal_ir": "Publicus/legal-ir-autoencoder",
}
LIBRARIES = dict(intent_ir="IntentIR", security_ir="SecurityIR", ui_ux_ir="UIUXIR", legal_ir="LegalIR")
CASES = ("without-interpretations", "with-explicit-interpretations")
AUTHORITY = ("qualified", "admitted", "proof_authority", "source_semantics_verified")
SUMMARY_SCOPE = (*AUTHORITY, "training_executed", "weights_changed", "new_holdout_evaluation",
                 "source_claims_all_proved", "context_inferred_by_model")
SCOPE = "one unchanged tuning prediction plus explicit authored interpretations"
ORIGINAL_CONTEXT = "517c09fa3397cba7d8ca6150115729bb7e8bed2ee8d2a28112d1df76b6a0d422"
ORIGINAL_CANDIDATE = "3cbbc43010f0a11fcb121b0e62b00eea3033cc22322ac37838e68a5bee36d3cd"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ref(data):
    return dict(sha256=sha(data), bytes=len(data))


def read_json(path):
    return json.loads(path.read_bytes())


def false_fields(value, fields, label):
    require(all(value.get(key) is False for key in fields), "unexpected or missing scope: " + label)


def identifier(value, size):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{" + str(size) + "}", value) is not None


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and str(path) == name and ".." not in path.parts and "\\" not in name


def snapshot(directory, expected):
    """Read only a closed evidence tree; unexpected files and symlinks block release."""
    require(directory.is_dir() and not directory.is_symlink(), "evidence directory absent or linked")
    files = {}
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "symlink in evidence: " + str(path))
        if path.is_dir():
            continue
        name = path.relative_to(directory).as_posix()
        require(path.is_file() and name in expected and safe_name(name), "unexpected evidence file: " + name)
        files[name] = path.read_bytes()
    require(set(files) == set(expected), "missing evidence files: " + str(sorted(set(expected) - set(files))))
    return files


def compact(report):
    rows = report["native_execution"]["per_projection"]
    syntax = [check for row in rows for check in row.get("additional_syntax_checks", [])]
    counterexamples = []
    for row in rows:
        for claim in (row.get("lowering") or {}).get("static_frame_interpretation", {}).get("claim_evaluations", []):
            if claim["counterexample_found"]:
                counterexamples.append(dict(projection_id=row["projection_id"], **claim,
                    generated_refutation_compiled=row["lake_status"] == "passed"))
    return dict(domain_id=report["domain_id"], source_sha256=report["source_sha256"],
        candidate_sha256=report["candidate_sha256"], context_sha256=report["context_sha256"],
        required_families=len(report["families"]), supported_families=sum(f["status"] == "supported" for f in report["families"]),
        all_requested_dependencies_supported=report["all_requested_dependencies_supported"],
        all_requested_native_checks_passed=report["all_requested_native_checks_passed"],
        native_projections=len(rows), complete_checks=sum(r["lake_status"] == "passed" and r["parser_status"] == "passed" for r in rows),
        sany_checks=len(syntax), sany_passed=sum(x["status"] == "passed" for x in syntax),
        protocol_counterexamples=counterexamples,
        unsupported_rows=[dict(projection_id=r["projection_id"], reason=r["reason"]) for r in rows if not r["semantic_lowering_supported"]],
        source_semantics_verified=False, proof_authority=False, admitted=False, qualified=False,
        context_inferred_by_model=False)


def validate_context(context, domain, candidate, source_text):
    false_fields(context, (*AUTHORITY, "promotion_performed"), "bound context")
    require(context["schema"] == "distributed-384-projection-context/v1", "unexpected context schema")
    require(context["domain_id"] == domain and context["candidate_sha256"] == sha(raw(candidate))
        and context["source_sha256"] == sha(source_text.encode()), "context source/candidate binding changed")
    require(context["context_sha256"] == sha(raw({k: v for k, v in context.items() if k != "context_sha256"})),
        "context digest differs")
    models = context["inputs"].get("supplemental_inputs", [])
    for row in context["inputs"].get("supplemental_interpretations", []):
        matching = [m for m in models if m["kind"] == row["kind"]]
        require(len(matching) == 1 and row["interpretation"]["native_document_sha256"] == sha(raw(matching[0]["document"])),
            "interpretation native document binding changed")


def validate_report(report, files, native_prefix, library, context, candidate, source_text):
    false_fields(report, (*AUTHORITY, "promotion_performed", "execution_authority", "target_rewritten",
        "context_inferred_by_model", "supplemental_interpretations_inferred", "saved_receipt_is_live_authority"), "candidate report")
    require(report["report_sha256"] == sha(raw({k: v for k, v in report.items() if k != "report_sha256"})),
        "report identity differs")
    validate_context(context, report["domain_id"], candidate, source_text)
    require(all(report[k] == context[k] for k in ("domain_id", "candidate_sha256", "source_sha256", "context_sha256")),
        "report context binding changed")
    execution = report["native_execution"]
    require(execution["schema"] == "distributed-384-candidate-native-lake/v3", "unexpected native gate schema")
    receipt = json.loads(files[native_prefix + "/receipt.json"])
    lean = files[native_prefix + "/" + library + ".lean"]
    require(receipt["lean_source"].encode() == lean and receipt["lean_source_sha256"] == sha(lean), "Lean/receipt differs")
    require({k: v for k, v in receipt.items() if k != "lean_source"} == execution, "receipt/report execution differs")
    for claim in compact(report)["protocol_counterexamples"]:
        false_fields(claim, ("equivalent_proved", "process_equivalence_verified"), "protocol counterexample")
        require(claim["generated_refutation_compiled"] is True and claim["counterexample_found"] is True,
            "counterexample proof was not compiled")
        require((claim["query_symbol"] + "_not_equivalent").encode() in lean, "checked refutation omitted from Lean artifact")


def validate_run(root, run, previous):
    """Capture the completed run and cross-check every scope before any staging."""
    run_directory = root / run
    summary_bytes = (run_directory / "summary.json").read_bytes()
    summary = json.loads(summary_bytes)
    require(summary["schema"] == "distributed384-explicit-native-interpretations-evidence/v1", "unexpected run schema")
    false_fields(summary, SUMMARY_SCOPE, "completed run")
    require(summary["original_native_reports_equal"] is True, "original native reports were changed")
    require([row["name"] for row in summary["authored"]] == list(CASES), "expected exactly both authored controls")
    require(len(summary["checkpoints"]) == 4 and {r["domain_id"] for r in summary["checkpoints"]} == set(DOMAINS),
        "incomplete or repeated checkpoint run")
    authored_files, authored_reports, authored_contexts, originals = {}, [], [], []
    for name, result in zip(CASES, summary["authored"]):
        expected = {"source-candidate.json", "context.json", "report.json", "summary.json", "native/receipt.json", "native/SecurityIR.lean"}
        files = snapshot(run_directory / "authored" / name, expected)
        original, context, report = (json.loads(files[key]) for key in ("source-candidate.json", "context.json", "report.json"))
        false_fields(original, (*AUTHORITY, "promotion_performed"), "authored source candidate")
        validate_report(report, files, "native", "SecurityIR", context, original["candidate_ir"], original["source_text"])
        expected_summary = dict(name=name, original_models_rewritten=False, learned_output=False, **compact(report))
        require(result == expected_summary == json.loads(files["summary.json"]), "authored summary differs from full report")
        authored_files.update({"authored/" + name + "/" + key: value for key, value in files.items()})
        originals.append(original)
        authored_contexts.append(context)
        authored_reports.append(report)
    require(originals[0] == originals[1] and summary["authored"][0]["candidate_sha256"] == ORIGINAL_CANDIDATE,
        "original authored candidate changed")
    require(authored_contexts[0]["context_sha256"] == ORIGINAL_CONTEXT, "original authored context changed")
    require(authored_reports[0]["native_report"] == authored_reports[1]["native_report"], "native reports differ")
    interpreted = deepcopy(authored_contexts[1]["inputs"])
    rows = interpreted.pop("supplemental_interpretations")
    require(len(rows) == 3 and {r["kind"] for r in rows} == {"protocol", "concurrency", "refinement"},
        "expected three explicit interpretation declarations")
    require(interpreted == authored_contexts[0]["inputs"], "original native declarations changed")
    before, after = summary["authored"]
    require(before["all_requested_native_checks_passed"] is False and before["supported_families"] == 13
        and before["complete_checks"] == 16 and before["native_projections"] == 19, "unexpected unchanged control outcome")
    require(after["all_requested_native_checks_passed"] is True and after["supported_families"] == 16
        and after["complete_checks"] == 19 and after["native_projections"] == 19, "interpreted control incomplete")
    require(any(x["claim_id"] == "claim:equivalence" for x in after["protocol_counterexamples"]),
        "original false protocol-equivalence claim was not retained")
    results = []
    for domain in DOMAINS:
        result = next(row for row in summary["checkpoints"] if row["domain_id"] == domain)
        directory = run_directory / "checkpoints" / domain
        checks_summary = read_json(directory / "checks/summary.json")
        require(checks_summary["rows"] == 1 and len(checks_summary["records"]) == 1, "one tuning prediction required")
        report_hash = checks_summary["records"][0]["report_sha256"]
        require(identifier(report_hash, 64), "invalid report identity")
        report_name = "checks/reports/" + report_hash + ".json"
        expected = {"declared-context.json", "published-checkpoint-reference.json", report_name,
            "checks/summary.json", "checks/contexts.json", "checks/inference.json", "checks/inference-inputs.json",
            "checks/job.json", "checks/native-0/receipt.json", "checks/native-0/" + LIBRARIES[domain] + ".lean"}
        if domain == "intent_ir":
            expected.add("authored-world-model.json")
        files = snapshot(directory, expected)
        require(checks_summary == json.loads(files["checks/summary.json"]), "summary changed while taking snapshot")
        old = read_json(previous / domain / "merged-result.json")
        plan = read_json(previous / domain / "coordinator/plan.json")
        published = json.loads(files["published-checkpoint-reference.json"])
        require(published == old["publication"] and published["repository_id"] == REPOSITORIES[domain]
            and published["repo_type"] == "model" and published["kind"] == "checkpoint"
            and identifier(published["revision"], 40) and identifier(published["manifest_sha256"], 64),
            "immutable checkpoint reference changed")
        require(published["binding"]["plan_id"] == plan["plan_id"] == old["plan_id"] == checks_summary["plan_id"]
            and identifier(plan["plan_id"], 64), "checkpoint plan binding changed")
        require(published["binding"]["domain_id"] == domain, "checkpoint domain binding changed")
        checkpoint_ref = ref(Path(old["checkpoint_path"]).read_bytes())
        require(checkpoint_ref == result["checkpoint"] == checks_summary["checkpoint"], "checkpoint bytes changed")
        manifest_path = previous / domain / "coordinator/bundles/checkpoints" / published["manifest_sha256"] / "manifest.json"
        checkpoint_manifest_bytes = manifest_path.read_bytes()
        checkpoint_manifest = json.loads(checkpoint_manifest_bytes)
        require(sha(checkpoint_manifest_bytes) == published["manifest_sha256"]
            and checkpoint_manifest["result"] == checkpoint_ref
            and checkpoint_manifest["binding"] == published["binding"], "published checkpoint manifest binding changed")
        false_fields(checks_summary, (*AUTHORITY, "promotion_performed", "target_access", "source_model_fidelity_verified",
            "context_inferred_by_model"), "checkpoint checks")
        require(checks_summary["evaluation_scope"] == "training_round_tuning_predictions_with_explicit_optional_declarations"
            and checks_summary["selected_subset"] is True, "unexpected checkpoint evaluation scope")
        report = json.loads(files[report_name])
        require(report["report_sha256"] == report_hash, "report filename binding differs")
        inputs, inference = json.loads(files["checks/inference-inputs.json"]), json.loads(files["checks/inference.json"])
        require(len(inputs) == len(inference) == 1 and set(inputs[0]) == {"id", "source_text", "embedding"},
            "inference input contains target or unreviewed rows")
        validation = read_json(previous / domain / "coordinator/validation.json")
        expected_input = {k: validation[0][k] for k in ("id", "source_text", "embedding")}
        require(inputs[0] == expected_input and inference[0]["id"] == inputs[0]["id"], "prediction is not the original first tuning row")
        false_fields(inference[0], (*AUTHORITY, "target_access", "teacher_forcing", "publication_performed"), "inference")
        context_batch = json.loads(files["declared-context.json"])
        require(context_batch == json.loads(files["checks/contexts.json"])
            and context_batch["plan_id"] == plan["plan_id"]
            and context_batch["checkpoint_sha256"] == checkpoint_ref["sha256"]
            and len(context_batch["rows"]) == 1 and context_batch["rows"][0]["id"] == inputs[0]["id"], "declared batch differs")
        context = context_batch["rows"][0]["context"]
        validate_report(report, files, "checks/native-0", LIBRARIES[domain], context, inference[0]["candidate_ir"], inputs[0]["source_text"])
        expected_result = dict(checkpoint=checkpoint_ref, rows=1, scope=SCOPE,
            source_native_models_rebound_for_this_CodeUnit=domain == "security_ir", **compact(report))
        require(result == expected_result, "checkpoint summary differs from full report")
        require(result["all_requested_native_checks_passed"] is True
            and result["all_requested_dependencies_supported"] is True, "checkpoint native checks incomplete")
        if domain == "security_ir":
            require(result["protocol_counterexamples"] == after["protocol_counterexamples"], "checkpoint counterexample dropped or changed")
        source = plan["dataset"]["source"]
        require(source["redistribution_allowed"] is True and source["source_path"] == "tests/fixtures/logic/source_reconstruction_v3.py"
            and source["source_repository"] == "https://github.com/endomorphosis/ipfs_datasets_py"
            and identifier(source["source_revision"], 40), "unreviewed source provenance")
        require("Authored" in source["description"] and "no test/canary rows" in source["provenance_review"],
            "source controls/holdout provenance differs")
        package_files = {"checkpoint-prediction/" + name: data for name, data in files.items()}
        package_files.update({"reproduce.py": (root / "reproduce.py").read_bytes(),
            "run-summary.json": summary_bytes, "result.json": raw(result),
            "source-provenance.json": raw(source), "published-checkpoint-reference.json": raw(published),
            "published-checkpoint-manifest.json": checkpoint_manifest_bytes})
        if domain == "security_ir":
            package_files.update(authored_files)
        results.append(dict(domain=domain, plan_id=plan["plan_id"], published=published,
            checkpoint=checkpoint_ref, files=package_files, result=result))
    require((run_directory / "summary.json").read_bytes() == summary_bytes, "completed run changed during snapshot")
    return summary, results


def bundle_files(files):
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name, data in sorted(files.items()):
                require(safe_name(name), "unsafe archive path")
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
                tar.addfile(entry, io.BytesIO(data))
    return compressed.getvalue()


def verify_archive(bundle, manifest):
    require(ref(bundle) == {k: manifest["archive"][k] for k in ("sha256", "bytes")}, "archive hash/length differs")
    expected = {row["path"]: row for row in manifest["files"]}
    require(len(expected) == len(manifest["files"]), "duplicate manifest member")
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as tar:
        members = tar.getmembers()
        require(len(members) == len(expected) and {m.name for m in members} == set(expected), "archive members differ")
        for member in members:
            require(member.isfile() and safe_name(member.name), "unsafe archive member")
            data = tar.extractfile(member).read()
            require(ref(data) == {k: expected[member.name][k] for k in ("sha256", "bytes")}, "archive member changed: " + member.name)


def prepare_packages(summary, records, code_commit):
    require(identifier(code_commit, 40), "immutable tested Git source commit required")
    packages = []
    for record in records:
        domain, files = record["domain"], record["files"]
        manifest = dict(schema="distributed384-richer-native-development-evidence/v1", domain_id=domain,
            plan_id=record["plan_id"], checkpoint=record["checkpoint"], published_checkpoint=record["published"],
            code_repository="https://github.com/endomorphosis/ipfs_datasets_py", code_commit=code_commit,
            candidate_gate_schema="distributed-384-candidate-native-lake/v3",
            scope="one unchanged authored tuning prediction with explicit caller declarations; Security also includes original-context and interpreted-context controls",
            source_provenance="published authored source_reconstruction_v3 controls plus repository-owned native fixtures; not full upstream corpora or a holdout evaluation",
            context_scope="authored declarations; Intent has an explicit authored world model; Security rebinds authored richer models to its CodeUnit",
            native_check_scope="native syntax/type/kernel checks; includes the checked refutation of a protocol static-frame-equivalence claim",
            security_claim_scope="the authored static observation frames are distinguishable; process equivalence and source security are not verified",
            formulas_and_supplemental_models_are_caller_declarations=True,
            interpretation_context_is_explicit=True, original_authored_native_reports_equal=True,
            context_inferred_by_model=False, source_claims_all_proved=False,
            training_executed=False, weights_changed=False, weights_included=False, training_target_rows_included=False,
            model_source_semantic_fidelity_verified=False, new_holdout_evaluation=False,
            all_requested_dependencies_supported=record["result"]["all_requested_dependencies_supported"],
            all_requested_native_checks_passed=record["result"]["all_requested_native_checks_passed"],
            result=record["result"], authored_controls=summary["authored"] if domain == "security_ir" else [],
            qualified=False, admitted=False, proof_authority=False, promotion_performed=False, source_semantics_verified=False,
            files=[dict(path=name, **ref(data)) for name, data in sorted(files.items())])
        bundle = bundle_files(files)
        manifest["archive"] = dict(path="evidence.tar.gz", **ref(bundle))
        verify_archive(bundle, manifest)
        manifest_bytes = raw(manifest)
        identity = sha(manifest_bytes)
        prefix = "training/structured384/" + record["plan_id"] + "/projection-checks/" + identity
        packages.append(dict(domain=domain, prefix=prefix, manifest=manifest, published=record["published"],
            checkpoint=record["checkpoint"], desired={prefix + "/manifest.json": manifest_bytes, prefix + "/evidence.tar.gz": bundle},
            receipt=dict(repository_id=REPOSITORIES[domain], repo_type="model", path=prefix,
                manifest_sha256=identity, archive_sha256=sha(bundle), archive_bytes=len(bundle), uploaded=False)))
    return packages


def bounded_snapshot(path, data):
    if path.exists():
        require(not path.is_symlink() and path.read_bytes() == data, "existing staged evidence differs: " + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)


def verify_published_checkpoint(package, download):
    published = package["published"]
    def fetch(name):
        return Path(download(repo_id=published["repository_id"], repo_type="model",
            filename=name, revision=published["revision"])).read_bytes()
    data = fetch(published["manifest_path_in_repo"])
    require(sha(data) == published["manifest_sha256"], "immutable remote checkpoint manifest differs")
    manifest = json.loads(data)
    require(manifest["binding"] == published["binding"] and manifest["result"] == package["checkpoint"],
        "remote checkpoint binding differs")
    payload = fetch(str(PurePosixPath(published["manifest_path_in_repo"]).parent / "payload.json"))
    require(ref(payload) == manifest["payload"], "remote checkpoint payload differs")


def upload_package(package, api, download, operation):
    repo, desired = package["receipt"]["repository_id"], package["desired"]
    info = api.model_info(repo)
    require(identifier(info.sha, 40), "immutable repository parent revision required")
    existing = {entry.rfilename for entry in info.siblings}
    if set(desired) & existing:
        require(set(desired) <= existing, "partial publication requires investigation")
        revision = info.sha
    else:
        result = api.create_commit(repo_id=repo, repo_type="model", parent_commit=info.sha,
            operations=[operation(path_in_repo=name, path_or_fileobj=io.BytesIO(data)) for name, data in desired.items()],
            commit_message="Archive explicit native interpretation checks and protocol counterexample")
        revision = result.oid
    require(identifier(revision, 40), "immutable published revision required")
    fetched = {}
    for name, data in desired.items():
        downloaded = Path(download(repo_id=repo, repo_type="model", filename=name, revision=revision)).read_bytes()
        require(downloaded == data, "published artifact verification failed: " + name)
        fetched[PurePosixPath(name).name] = downloaded
    manifest = json.loads(fetched["manifest.json"])
    verify_archive(fetched["evidence.tar.gz"], manifest)
    return dict(package["receipt"], uploaded=True, revision=revision, download_verified=True,
        archive_members_download_verified=len(manifest["files"]), immutable_checkpoint_reference_download_verified=True,
        url="https://huggingface.co/" + repo + "/blob/" + revision + "/" + package["prefix"] + "/manifest.json")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--run", default="run-01", help="completed run directory beneath --root")
    parser.add_argument("--previous", type=Path,
        default=Path("/home/barberb/lift_coding/artifacts/distributed384-20261001/run-01"))
    parser.add_argument("--code-commit", help="full immutable Git commit used for the checked source")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true", help="offline checks only; no staging or upload")
    mode.add_argument("--upload", action="store_true", help="stage, then append evidence with parent-commit CAS")
    args = parser.parse_args(argv)
    require(safe_name(args.run) and len(PurePosixPath(args.run).parts) == 1, "a single run directory name is required")
    if not args.validate_only:
        require(identifier(args.code_commit, 40), "--code-commit is required for staging or upload")
    summary, records = validate_run(args.root, args.run, args.previous)
    if args.validate_only:
        print(json.dumps(dict(validated=True, staged=False, uploaded=False,
            domains=[r["domain"] for r in records], files={r["domain"]: len(r["files"]) for r in records})))
        return
    packages = prepare_packages(summary, records, args.code_commit)
    # Check all stage paths before writing any new artifact.
    for package in packages:
        stage = args.root / "publication" / package["domain"]
        for name, data in package["desired"].items():
            path = stage / PurePosixPath(name).name
            if path.exists():
                require(not path.is_symlink() and path.read_bytes() == data, "existing staged evidence differs: " + str(path))
    for package in packages:
        stage = args.root / "publication" / package["domain"]
        for name, data in package["desired"].items():
            bounded_snapshot(stage / PurePosixPath(name).name, data)
    if args.upload:
        from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download
        api = HfApi()
        # Validate all four immutable parent checkpoint references before the first write.
        for package in packages:
            verify_published_checkpoint(package, hf_hub_download)
    receipts = []
    for package in packages:
        receipt_path = args.root / "publication" / package["domain"] / "receipt.json"
        receipt = package["receipt"]
        if args.upload:
            receipt = upload_package(package, api, hf_hub_download, CommitOperationAdd)
        elif receipt_path.exists():
            previous_receipt = read_json(receipt_path)
            require(all(previous_receipt[k] == receipt[k] for k in receipt if k != "uploaded"), "staged receipt identity differs")
            if previous_receipt.get("uploaded") is True:
                receipt = previous_receipt
        receipt_path.write_bytes(raw(receipt))
        receipts.append(receipt)
        print(json.dumps(receipt), flush=True)
    (args.root / "publication/receipts.json").write_bytes(raw(receipts))


if __name__ == "__main__":
    main()
