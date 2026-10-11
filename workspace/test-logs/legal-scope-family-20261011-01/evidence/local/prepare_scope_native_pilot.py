"""Prepare saved native parser views; execute no models, compiler or subprocesses.

This helper deliberately omits shared-scope and statutory-preflight runtime.
It prepares twelve bounded parser requests, retaining all twenty-four declared
attempts and all sixteen exposed-law dispositions. No registered temporal/event
family, legal accuracy, authenticated model or review, or admission is claimed.
Run only after independent review of this frozen helper and its source owners.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

from bootstrap_inert import install, ROOT, PACKAGES

F = Path(__file__).resolve().parent
PARENT = F.parent / "legal-formal-output-20261011-01"
R = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/structured-probability-20261011-01/results")
OUT = F / "prepared-native-views-v01"
CHECKPOINT_CANONICAL_SHA256 = "89ba30be1de11b6f9f52263138a41cbc286a1c9bd48981801ab54ff7b11a9630"
TOOLCHAIN = "leanprover/lean4:v4.34.1"
PROFILES = ("tdfol", "dcec")
DENIED_NUMERICAL_ROOTS = {"torch", "numpy", "transformers", "sentence_transformers", "tensorflow", "jax"}
MAX_JSON_BYTES = 32 * 1024**2

# These are external file identities, distinct from owners' canonical content
# digests. The checkpoint is SHA-checked as bytes only, never JSON-decoded.
FROZEN_INPUTS = {
    "development_source": (F / "authored-development-source-only-v02.json", 4968, "34fe6b7255c89292c148e79070f657104ba8a7855f44d936168309246bd31e5d"),
    "development_declarations": (F / "authored-development-cue-declarations-v02.json", 9753, "67b80ed4224b3d04f636d980dd66b323ca6c1786fc058407782b8f13a7170756"),
    "statutory_source": (F / "statutory-source-only-inputs.json", 4311, "8e32b64579eb67b604d7ba7cd907d17da7c8934e354b0641cd344b6522049fc3"),
    "bootstrap": (F / "bootstrap_inert.py", 1208, "030ac4f55adf5bf305bab0fcef9e33daa27c8fd083ddd474eac623e754246da1"),
    "original_full_tuning_report": (R / "source_only-1729-ce0-tuning-greedy.json", 874913, "5a127645d451907b79a7cdca4ab64f61f4c0f0ec181ea31e1e101a4aa97907d8"),
    "original_checkpoint_file": (R / "source_only-1729-ce0-checkpoint.json", 4117352, "89ba30be1de11b6f9f52263138a41cbc286a1c9bd48981801ab54ff7b11a9630"),
    "original_statutory_raw_report": (R / "source_only-1729-ce0-law-none.json", 274731, "b9ec06cb84136161a167b243775f5428f607cbb7d770a4c53a4cf59da88ae710"),
    "original_statutory_joint_report": (R / "source_only-1729-ce0-law-none-joint.json", 103504, "7ee549b131396a70dedcda7550e3ed5a3e32d6910c3118940a82dcf53847599a"),
    "prior_preparation_summary": (PARENT / "prepared-pilot-v01/preparation-summary.json", 64357, "82fcae238ba6e87d6eb44f97ee0b0da91ead6c1ba35367b7a695b2d7d99f879b"),
    "prior_empty_review_preflight": (PARENT / "prepared-pilot-v01/actual-statutory-preflight.json", 47619, "d7488d74d6418d61992e840bf26bc4ec9140ba704eb39e244e45761b8775a1fd"),
    "prior_empty_review_replay": (PARENT / "prepared-pilot-v01/actual-statutory-preflight-replay.json", 1997, "018196a7576181f78a9891b122e299fc1059a1723d121156dcef259126775644"),
    "old_source_owner_ledger": (PARENT / "retained-owner-pins.json", 19233, "331302c6dedeb21980062be387e92e2cac9c88bd7b8f78b4a8f7250e49af6305"),
    "new_native_view_source": (ROOT / "ipfs_datasets_py/logic/legal_ir/saved_span_native_views.py", 13297, "049260f3a683d58a906290436667804f410d4839161cfe7e2202b37b7f892d6d"),
    "new_native_view_tests": (ROOT / "tests/unit/logic/legal_ir/test_saved_span_native_views.py", 29921, "6fa7b07bd5f3bfc3c750f65cb99917cdfaa07bd370e2321529775ad338707a90"),
}


def pin(path):
    path = Path(path)
    assert path.is_absolute() and path.is_file() and not path.is_symlink() and path.resolve() == path, path
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def expected_pin(spec):
    path, size, sha = spec
    return {"path": str(path), "bytes": size, "sha256": sha}


def read_json(path):
    raw = Path(path).read_bytes()
    assert 0 < len(raw) <= MAX_JSON_BYTES

    def pairs(items):
        result = {}
        for key, value in items:
            assert key not in result, "duplicate JSON key"
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON literal: " + value)

    result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    json.dumps(result, allow_nan=False)
    return result


def output_path(name):
    relative = Path(name)
    assert not relative.is_absolute() and relative.parts and all(part not in (".", "..") for part in relative.parts)
    result = OUT / relative
    result.parent.mkdir(parents=True, exist_ok=True)
    assert result.parent.resolve() == result.parent and not result.parent.is_symlink()
    return result


def write_bytes(name, raw):
    assert type(raw) is bytes
    path = output_path(name)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return pin(path)


def write_json(name, value):
    raw = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    assert len(raw) <= MAX_JSON_BYTES
    return write_bytes(name, raw)


def audit(event, values):
    if event.startswith("socket.") or event.startswith("subprocess.") or event in {
        "os.system", "os.fork", "os.forkpty", "os.posix_spawn", "os.exec", "os.spawn", "pty.spawn"
    }:
        raise AssertionError("saved preparation cannot use network or external processes: " + event)
    if event == "import" and values and str(values[0]).split(".")[0] in DENIED_NUMERICAL_ROOTS:
        raise AssertionError("numerical backend prohibited: " + str(values[0]))


def must_refuse(case, call, needle=None):
    try:
        call()
    except ValueError as error:
        if needle is not None:
            assert needle in str(error), (case, str(error))
        return {"case": case, "refused": True, "reason": str(error),
                "model_calls": 0, "backend_calls": 0, "admitted": False}
    raise AssertionError("expected refusal: " + case)


def source_endpoints(prior_summary, old_ledger):
    """Rebind saved source byte identities to this isolated checkout, not old receipt bodies."""
    expected = {}
    prior_root = PARENT / "datasets"
    for name, old in dict(old_ledger, **prior_summary["loaded_producer_pins"]).items():
        old_path = Path(old["path"])
        relative = old_path.relative_to(prior_root)
        current = ROOT / relative
        wanted = {"path": str(current), "bytes": old["bytes"], "sha256": old["sha256"]}
        assert pin(current) == wanted, (name, current)
        expected[name] = wanted
    name = "ipfs_datasets_py.logic.legal_ir.saved_span_native_views"
    expected[name] = expected_pin(FROZEN_INPUTS["new_native_view_source"])
    return expected


def main():
    # Installation and producer imports occur only in this explicit reviewed
    # entry point. This authoring step does not invoke main.
    sys.addaudithook(audit)
    assert not (DENIED_NUMERICAL_ROOTS & set(sys.modules))
    input_pins = {name: pin(spec[0]) for name, spec in FROZEN_INPUTS.items()}
    assert all(input_pins[name] == expected_pin(spec) for name, spec in FROZEN_INPUTS.items())
    input_pins["preparation_helper"] = pin(Path(__file__).resolve())
    prior_summary = read_json(FROZEN_INPUTS["prior_preparation_summary"][0])
    old_ledger = read_json(FROZEN_INPUTS["old_source_owner_ledger"][0])
    assert len(old_ledger) == 62
    source_before = source_endpoints(prior_summary, old_ledger)
    assert prior_summary["passed"] is True and prior_summary["source_only_dimension"] == 384
    assert prior_summary["source_only_latent_enabled"] is False
    assert prior_summary["checkpoint_canonical_sha256"] == CHECKPOINT_CANONICAL_SHA256
    state_file_pin = input_pins["original_checkpoint_file"]
    assert state_file_pin in prior_summary["input_pins"]
    checkpoint_binding = {
        "file_pin": state_file_pin, "canonical_sha256": CHECKPOINT_CANONICAL_SHA256,
        "configuration_metadata_receipt": input_pins["prior_preparation_summary"],
        "latent_dimension": 384, "latent_enabled": False,
        "current_file_byte_sha_verified": True, "checkpoint_JSON_decoded": False,
        "canonical_checkpoint_digest_recomputed": False, "tensors_loaded": False,
        "model_or_checkpoint_authenticated": False,
    }
    install()
    namespace_objects = {name: sys.modules[name] for name in PACKAGES}
    from ipfs_datasets_py.logic.legal_ir import saved_span_family_adapter as adapter
    from ipfs_datasets_py.logic.legal_ir import saved_span_native_views as views
    from ipfs_datasets_py.logic.autoformal import legal_source_family_bridge as bridge
    from ipfs_datasets_py.logic.autoformal import legal_source_family_lake as gate

    assert not OUT.exists()
    OUT.mkdir()
    inputs = read_json(FROZEN_INPUTS["development_source"][0])
    declarations = read_json(FROZEN_INPUTS["development_declarations"][0])
    raw = read_json(FROZEN_INPUTS["original_full_tuning_report"][0])
    assert inputs["parent_saved_inference_report"] == input_pins["original_full_tuning_report"]
    assert len(inputs["rows"]) == len(declarations["rows"]) == 12
    assert inputs["selected_original_positions"] == list(range(12))
    assert inputs["predeclared_native_positions"] == list(range(9))
    assert inputs["predeclared_temporal_refusal_positions"] == [9, 10, 11]
    assert inputs["semantic_gold"] is inputs["training_or_evaluation_admission"] is False
    assert declarations["source_semantics_verified"] is declarations["training_or_evaluation_admission"] is False
    assert declarations["reviewer_authentication"] is False
    assert inputs["new_model_calls"] == 0 and inputs["latent_vectors_exported"] is False
    assert inputs["canonical_supervised_targets_exported"] is False
    assert len(raw["rows"]) == inputs["full_report_rows_preserved"] == 96
    assert raw["checkpoint_sha256"] == inputs["checkpoint_canonical_sha256"] == CHECKPOINT_CANONICAL_SHA256
    raw_digest = adapter.digest(raw)
    requests, attempts, eligible_rows, positive = [], [], [], []
    for source, supplied in zip(inputs["rows"], declarations["rows"], strict=True):
        position = supplied["position"]
        assert type(position) is int and 0 <= position < 12
        assert source["id"] == supplied["id"] == raw["rows"][position]["id"]
        assert source["source_sha256"] == raw["rows"][position]["source_sha256"]
        assert supplied["modality_span"]["canonical_value"] == raw["rows"][position]["decoder_row"]["canonical_ir"]["rules"][0]["modality"]

        def pending():
            return adapter.prepare_pending(source, raw, expected_report_sha256=raw_digest,
                expected_checkpoint_sha256=CHECKPOINT_CANONICAL_SHA256, row_id=source["id"])

        if supplied["expected_bounded_profile_outcome"] == "temporal_refused":
            assert position in (9, 10, 11)
            refusal = must_refuse("unchanged_temporal_pending_profile", pending, "temporal")
            for profile in PROFILES:
                attempts.append({"id": source["id"], "original_position": position,
                    "native_parser_profile": profile, "status": "temporal_profile_refused",
                    "attempt_stage": "unchanged_pending_preparation", "native_view_API_called": False,
                    "refusal": deepcopy(refusal), "semantic_accuracy": None, "admitted": False})
            continue
        assert supplied["expected_bounded_profile_outcome"] == "native" and position < 9
        packet = pending()
        seal = adapter.digest(packet)
        assert adapter.validate_pending(packet, expected_packet_sha256=seal)
        declaration = adapter.declaration_skeleton(packet)
        declaration["occurrence"].update(occurrence_id=supplied["occurrence_id"],
            start_char=supplied["start_char"], end_char=supplied["end_char"], source_text=source["source_text"],
            modality_anchor=deepcopy(supplied["modality_span"]))
        interpretation = declaration["interpretation"]
        interpretation.update(activation_scope=bridge.ACTIVATION_SCOPE, exception_scope=bridge.EXCEPTION_SCOPE)
        for facet in ("conditions", "exceptions"):
            supplied_rows = supplied["qualifier_interpretations"][facet]
            assert [row["literal"] for row in supplied_rows] == [row["literal"] for row in interpretation["rules"][0][facet]]
            interpretation["rules"][0][facet] = deepcopy(supplied_rows)
        saved_pins = [write_json(f"development/{position:02d}-pending.json", packet),
                      write_json(f"development/{position:02d}-declaration.json", declaration)]
        eligible_rows.append({"id": source["id"], "original_position": position,
                              "packet_sha256": seal, "outputs": saved_pins})
        for profile in PROFILES:
            if profile == "dcec" and position >= 3:
                refusal = must_refuse("DCEC_qualifier_refusal", lambda: views.prepare_native_view(packet, declaration,
                    expected_packet_sha256=seal, native_parser_profile=profile), "qualifier-free")
                attempts.append({"id": source["id"], "original_position": position,
                    "native_parser_profile": profile, "status": "qualified_DCEC_profile_refused",
                    "attempt_stage": "native_view_preparation", "native_view_API_called": True,
                    "refusal": refusal, "packet_sha256": seal, "outputs": deepcopy(saved_pins),
                    "semantic_accuracy": None, "admitted": False})
                continue
            result = views.prepare_native_view(packet, declaration, expected_packet_sha256=seal,
                                               native_parser_profile=profile)
            assert views.validate_native_view(result, packet, declaration, expected_packet_sha256=seal,
                                              native_parser_profile=profile)
            assert result["sealed_legal_family"] == result["sealed_route"]["family_id"] == "deontic"
            assert result["canonical_ir"] == raw["rows"][position]["decoder_row"]["canonical_ir"]
            assert all(result[key] is False for key in views.FALSE)
            request = deepcopy(result["request"])
            request["family"] = profile
            requests.append(request)
            positive.append((position, packet, declaration, result))
            result_pin = write_json(f"development/{position:02d}-{profile}-native-view.json", result)
            attempts.append({"id": source["id"], "original_position": position,
                "native_parser_profile": profile, "status": "native_parser_view_prepared",
                "attempt_stage": "native_view_preparation", "native_view_API_called": True,
                "packet_sha256": seal, "outputs": [*deepcopy(saved_pins), result_pin],
                "registry_family_qualified": False, "sealed_legal_family": "deontic",
                "semantic_accuracy": None, "admitted": False})
    assert len(attempts) == 24 and len(eligible_rows) == 9 and len(requests) == len(positive) == 12
    assert [(row["original_position"], row["native_parser_profile"]) for row in attempts] == [
        (position, profile) for position in range(12) for profile in PROFILES]
    assert sum(row["status"] == "temporal_profile_refused" for row in attempts) == 6
    assert sum(row["status"] == "qualified_DCEC_profile_refused" for row in attempts) == 6
    assert sum(request["family"] == "tdfol" for request in requests) == 9
    assert sum(request["family"] == "dcec" for request in requests) == 3
    write_json("development-attempts.json", attempts)
    write_json("development-packet-declarations.json", eligible_rows)

    negative = []
    _, packet, declaration, result = positive[0]
    seal = adapter.digest(packet)
    for profile in ("TDFOL", "event_calculus", "fol", "deontic_fol"):
        negative.append(must_refuse("native_parser_alias_" + profile, lambda profile=profile:
            views.prepare_native_view(packet, declaration, expected_packet_sha256=seal,
                                      native_parser_profile=profile), "native_parser_profile"))
    bad = deepcopy(declaration)
    bad["occurrence"]["modality_anchor"]["end_char"] += 1
    negative.append(must_refuse("wrong_modality_literal", lambda: views.prepare_native_view(packet, bad,
        expected_packet_sha256=seal, native_parser_profile="tdfol"), "interval"))
    bad = deepcopy(declaration)
    span = packet["facet_geometry"]["actor"]
    bad["occurrence"]["modality_anchor"] = {key: span[key] for key in ("start_char", "end_char", "source_text")}
    bad["occurrence"]["modality_anchor"]["canonical_value"] = "O"
    negative.append(must_refuse("cue_overlaps_actor", lambda: views.prepare_native_view(packet, bad,
        expected_packet_sha256=seal, native_parser_profile="tdfol"), "overlaps"))
    bad = deepcopy(declaration)
    bad["interpretation"]["modal_context"] = "guessed_context"
    negative.append(must_refuse("nonnull_context", lambda: views.prepare_native_view(packet, bad,
        expected_packet_sha256=seal, native_parser_profile="tdfol")))
    for family in PROFILES:
        negative.append(must_refuse("unsupported_sealed_family_" + family, lambda family=family:
            adapter.prepare_family(packet, declaration, expected_packet_sha256=seal, family=family)))
    _, qpacket, qdeclaration, _ = next(row for row in positive if row[0] == 3)
    bad = deepcopy(qdeclaration)
    bad["interpretation"]["rules"][0]["conditions"][0]["expression"] = None
    negative.append(must_refuse("unfilled_qualifier_expression", lambda: views.prepare_native_view(qpacket, bad,
        expected_packet_sha256=adapter.digest(qpacket), native_parser_profile="tdfol")))
    for mutation in ("registry_qualification", "native_ast", "request"):
        changed = deepcopy(result)
        if mutation == "registry_qualification": changed["registry_family_qualified"] = True
        elif mutation == "native_ast": changed["native_view"]["formulas"][0]["native_ast"]["operator"]["value"] = "P"
        else: changed["request"]["occurrence_bindings"][0]["facets"]["actor"]["start_char"] += 1
        changed["output_sha256"] = views.digest({key: value for key, value in changed.items() if key != "output_sha256"})
        negative.append(must_refuse("resealed_output_" + mutation, lambda changed=changed:
            views.validate_native_view(changed, packet, declaration, expected_packet_sha256=seal,
                                       native_parser_profile="tdfol"), "replay"))
    assert len(negative) == 13
    write_json("native-negative-controls.json", negative)

    compiler = gate.prepare_source_family_legal(requests, toolchain=TOOLCHAIN)
    gate.validate_preparation(compiler)
    manifest = compiler.to_dict()
    assert manifest["all_candidates_supported"] is True and manifest["target"] == "legal"
    assert manifest["status"] == "prepared" and manifest["backend_executed"] is False
    assert len(manifest["candidates"]) == 12
    expected_modules = ["LegalSourceFamily.Prelude", *[row["module"] for row in manifest["candidates"]], "LegalSourceFamily"]
    assert len(expected_modules) == len(set(expected_modules)) == 14
    files = dict(compiler.files)
    assert len(files) == 17
    assert {name.replace("/", ".")[:-5] for name in files if name.endswith(".lean")} == set(expected_modules)
    write_json("native-requests.json", requests)
    write_json("native-preparation-manifest.json", manifest)
    write_json("expected-native-modules.json", expected_modules)
    for name, body in compiler.files:
        raw_body = body.encode("utf-8")
        assert hashlib.sha256(raw_body).hexdigest() == manifest["file_sha256"][name]
        write_bytes("native-prepared/" + name, raw_body)
    blocked_requests = deepcopy(requests) + [dict(deepcopy(requests[0]), family="fol")]
    blocked = gate.prepare_source_family_legal(blocked_requests, toolchain=TOOLCHAIN)
    gate.validate_preparation(blocked)
    blocked_manifest = blocked.to_dict()
    assert blocked_manifest["status"] == "blocked" and blocked_manifest["all_candidates_supported"] is False
    assert blocked_manifest["backend_executed"] is False and set(dict(blocked.files)) == {"source-family-inputs.json"}
    write_json("all-or-none-unsupported-batch.json", blocked_manifest)

    real = read_json(FROZEN_INPUTS["statutory_source"][0])
    real_raw = read_json(FROZEN_INPUTS["original_statutory_raw_report"][0])
    joint = read_json(FROZEN_INPUTS["original_statutory_joint_report"][0])
    assert len(real["rows"]) == len(real_raw["rows"]) == len(joint["rows"]) == 8
    assert real["semantic_gold"] is real["target_labels_exported"] is False
    assert real_raw["checkpoint_sha256"] == CHECKPOINT_CANONICAL_SHA256
    dispositions = []
    for lane in ("raw", "joint"):
        for position, source in enumerate(real["rows"]):
            options = {"joint_report": joint, "expected_joint_report_sha256": adapter.digest(joint)} if lane == "joint" else {}
            base = {"id": source["id"], "position": position, "lane": lane,
                "original_saved_status": joint["rows"][position]["result"]["status"] if lane == "joint" else real_raw["rows"][position]["decoder_row"]["status"],
                "semantic_accuracy": None, "admitted": False, "declaration_filled": False,
                "compiler_executed": False, "registry_family_qualified": False}
            try:
                real_packet = adapter.prepare_pending(source, real_raw, expected_report_sha256=adapter.digest(real_raw),
                    expected_checkpoint_sha256=CHECKPOINT_CANONICAL_SHA256, row_id=source["id"], **options)
            except adapter.SavedSpanFamilyError as error:
                base.update(status="saved_proposal_or_profile_refused", reason=str(error))
            else:
                blank = adapter.declaration_skeleton(real_packet)
                real_seal = adapter.digest(real_packet)
                assert blank["occurrence"]["occurrence_id"] is None
                assert blank["occurrence"]["modality_anchor"]["start_char"] is None
                refusals = []
                for profile in PROFILES:
                    refusal = must_refuse("real_blank_declaration_" + profile, lambda profile=profile:
                        views.prepare_native_view(real_packet, blank, expected_packet_sha256=real_seal,
                                                  native_parser_profile=profile))
                    refusals.append({"native_parser_profile": profile, **refusal})
                base.update(status="pending_caller_declaration", blank_native_refusals=refusals,
                    outputs=[write_json(f"statutory/{lane}-{position:02d}-pending.json", real_packet),
                             write_json(f"statutory/{lane}-{position:02d}-blank-declaration.json", blank)])
            dispositions.append(base)
    assert len(dispositions) == 16
    assert sum(row["status"] == "pending_caller_declaration" for row in dispositions) == 5
    assert sum(row["status"] == "saved_proposal_or_profile_refused" for row in dispositions) == 11
    assert sum(len(row.get("blank_native_refusals", [])) for row in dispositions) == 10
    # Compare only source IDs, lane/order and dispositions, never old path-bearing
    # native reports or producer receipts from the prior isolated checkout.
    projection = lambda rows: [(row["id"], row["position"], row["lane"], row["status"], row.get("reason")) for row in rows]
    assert projection(dispositions) == projection(prior_summary["statutory_dispositions"])
    write_json("statutory-dispositions.json", dispositions)
    prior_review = read_json(FROZEN_INPUTS["prior_empty_review_preflight"][0])
    prior_replay = read_json(FROZEN_INPUTS["prior_empty_review_replay"][0])
    assert prior_review["status"] == "pending" and prior_review["item_count"] == 8
    assert prior_review["submission_count"] == prior_review["declaration_count"] == prior_review["gold_labels_created"] == 0
    assert all(type(value) is int and value == 0 for value in prior_review["admission_masks"].values())
    assert prior_replay["status"] == "validated_declared_preflight_only"
    assert prior_replay["admission_masks"] == prior_review["admission_masks"]
    review_metadata = {"scope": "Pinned prior empty review evidence only; this helper does not replay or create reviews/preflight/scope declarations.",
        "actual_review_items": 8, "actual_human_submissions": 0, "actual_semantic_labels": 0,
        "admission_masks": deepcopy(prior_review["admission_masks"]), "current_preflight_executed": False,
        "current_scope_API_executed": False, "prior_preflight_pin": input_pins["prior_empty_review_preflight"],
        "prior_replay_pin": input_pins["prior_empty_review_replay"]}
    write_json("prior-empty-review-metadata.json", review_metadata)

    assert not (DENIED_NUMERICAL_ROOTS & set(sys.modules))
    loaded, namespaces = {}, {}
    for name in PACKAGES:
        assert sys.modules[name] is namespace_objects[name]
        assert getattr(namespace_objects[name], "__spec__", None) is None
        path = Path(namespace_objects[name].__file__).resolve()
        namespaces[name] = {"declaration": "synthetic namespace; file body not executed",
            "declared_path": str(path), "file_endpoint_pin": pin(path) if path.is_file() else None}
    for name, module in list(sys.modules.items()):
        if not name.startswith("ipfs_datasets_py.") or name in PACKAGES:
            continue
        path = getattr(module, "__file__", None)
        if path is not None:
            assert name in source_before, ("unfrozen producer", name, path)
            current = pin(Path(path).resolve())
            assert current == source_before[name], ("changed producer", name)
            loaded[name] = current
    assert "ipfs_datasets_py.logic.legal_ir.saved_span_native_views" in loaded
    assert "ipfs_datasets_py.logic.legal_ir.statutory_declaration_preflight" not in loaded
    source_after = source_endpoints(prior_summary, old_ledger)
    assert source_before == source_after
    assert all(pin(spec[0]) == input_pins[name] for name, spec in FROZEN_INPUTS.items())
    assert pin(Path(__file__).resolve()) == input_pins["preparation_helper"]
    output_pins = [pin(path) for path in sorted(OUT.rglob("*")) if path.is_file()]
    summary = {"schema": "saved-span-native-parser-view-preparation-pilot/v1", "passed": True, "findings": [],
        "scope": "Saved source-only synthetic DEVELOPMENT predictions under explicit caller interpretations; exposed statutory proposals remain pending or refused.",
        "sealed_legal_family": "deontic", "registry_family_qualified": False,
        "parser_views_do_not_qualify_registered_families": True,
        "development_rows": 12, "development_requested": 12,
        "development_parser_attempts": 24, "development_outcomes": attempts,
        "eligible_packet_declaration_pairs": 9, "supported_parser_requests": 12,
        "native_requests_predeclared": 12,
        "TDFOL_ground_parser_requests": 9, "DCEC_qualifier_free_parser_requests": 3,
        "temporal_refused": 3, "temporal_refusal_attempts": 6, "DCEC_qualifier_refusal_attempts": 6,
        "full_original_report_rows": 96, "source_only_dimension": 384, "source_only_latent_enabled": False,
        "checkpoint_binding": checkpoint_binding,
        "expected_native_modules": expected_modules, "prepared_project_files": 17,
        "negative_controls": negative, "all_or_none_unsupported_batch_blocked": True,
        "statutory_dispositions": dispositions, "statutory_original_rows": 8, "statutory_lanes": 2,
        "statutory_pending_declarations": 5, "statutory_proposal_or_profile_refusals": 11,
        "statutory_blank_native_refusals": 10, "actual_review_metadata": review_metadata,
        "input_pins": list(input_pins.values()), "frozen_input_pins_by_role": input_pins,
        "source_endpoints_before": source_before, "source_endpoints_after": source_after,
        "loaded_producer_pins": loaded, "loaded_producer_endpoint_pins": loaded,
        "synthetic_namespace_endpoints": namespaces,
        "loaded_endpoint_scope": "Saved hashes of imported producer file endpoints, separate from synthetic namespace file endpoints; no continuous or authenticated execution provenance.",
        "output_pins": output_pins, "output_pins_excluding_summary_itself": output_pins,
        "model_calls": 0, "encoder_calls": 0, "optimizer_updates": 0,
        "compiler_executed": False, "preflight_runtime_executed": False, "scope_runtime_executed": False,
        "semantic_accuracy": None, "semantic_gold_created": False, "training_or_evaluation_admission": False,
        "proof_authority": False, "admitted": False, "cross_family_equivalence_verified": False,
        "cross_parser_AST_equality_asserted": False, "network_or_subprocess_calls": 0,
        "network_scope": "Python audit-hook denial of socket/process operations; no kernel network namespace claim.",
        "existing_native_gate_limits_unchanged": {"timeout_seconds": 60, "Lean_threads": 2,
            "sampled_tree_RSS_bytes": 2147483648, "max_workspace_bytes": 134217728,
            "max_output_bytes": 262144, "max_input_bytes": 8388608},
        "old_numerical_guardian_claims_or_caps_modified": False,
        "prior_deontic_build_scope": "The old nine deontic requests have a separate prior actual build; no old native receipts are regenerated or path-compared here.",
    }
    write_json("preparation-summary.json", summary)
    print("Prepared 12 parser requests / 14 expected modules; retained 24 attempts, 16 law dispositions and prior empty review evidence; no models or compiler calls.")


if __name__ == "__main__":
    main()
