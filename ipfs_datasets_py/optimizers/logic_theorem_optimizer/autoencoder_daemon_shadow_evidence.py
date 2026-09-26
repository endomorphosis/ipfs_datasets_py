"""Reconcile optional verifier shadow evidence before owner CAS staging.

This validates the exact outputs of the supervised, source-bound verifier. It
does not repeat its state replay, authenticate arbitrary receipt issuers, or
make a sparse artifact authoritative. The registered candidate stays complete.
"""
from __future__ import annotations

from .autoencoder_daemon_invocation_contracts import (
    DaemonInvocationError, MAX_CHECKPOINT_BYTES, MAX_RESULT_BYTES, RESULT_SCHEMA, SHADOW_REQUEST_SCHEMA,
    WEIGHT_REQUEST_SCHEMA,
    canonical, digest, parse_json, reference, safe_path, verify,
)


def _require(condition, message):
    if not condition:
        raise DaemonInvocationError("sparse shadow: " + message)


def _same(left, right):
    return canonical(left) == canonical(right)


def _content(ref):
    return {key: ref[key] for key in ("sha256", "bytes")}


def shadow_provenance(*, request_ref, launch_ref, native_result_ref):
    return {"integration": "owned-daemon-independent-verifier-v1",
            "request": _content(request_ref), "launch": _content(launch_ref),
            "native_result": _content(native_result_ref)}


def _snapshot(value, identity, names):
    from .modal_autoencoder_state_diff import PROFILE, MAX_COMPONENT_BYTES, MAX_STATE_BYTES
    _require(type(value) is dict and value.get("profile") == PROFILE,
             "raw snapshot profile differs")
    _require(_same(value.get("component_fields"), names)
             and type(value.get("component_count")) is int and value["component_count"] == 38
             and type(value.get("components")) is dict and set(value["components"]) == set(names),
             "raw snapshot component inventory differs")
    total = 0
    for item in value["components"].values():
        _require(type(item) is dict and set(item) == {"sha256", "encoded_bytes"},
                 "raw component descriptor differs")
        reference({"sha256": item["sha256"], "bytes": item["encoded_bytes"]}, MAX_COMPONENT_BYTES)
        total += item["encoded_bytes"]
    _require(total <= MAX_STATE_BYTES and _same(value.get("total_encoded_bytes"), total),
             "raw snapshot byte accounting differs")
    _require(value.get("raw_state_sha256") == digest({"profile": PROFILE, "components": value["components"]}),
             "raw snapshot aggregate differs")
    _require(_same(value.get("plain_identity"), identity)
             and _same(value.get("state_revision"), identity["revision"]),
             "endpoint identity or revision differs")


def validate_owned_shadow_evidence(value, *, request, launch_ref, native_result_ref,
                                   candidate, independent, attempt):
    """Return original patch/receipt descriptors for staged completion evidence.

    Called only after the owner has checked the supervised verifier result's
    immutable descriptor. Source/lease authority remains with that invocation.
    """
    from .modal_autoencoder import MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS
    from .modal_autoencoder_patch_codec import MAX_PATCH_BYTES, decode_patch
    from .modal_autoencoder_state_diff import PROFILE
    from .autoencoder_daemon_sparse_shadow import SCHEMA
    _require(request["schema"] in (SHADOW_REQUEST_SCHEMA, WEIGHT_REQUEST_SCHEMA)
             and request.get("sparse_shadow") is True,
             "request did not enable shadow")
    request_ref = independent_request(launch_ref)
    _require(independent.get("schema") == RESULT_SCHEMA and independent.get("mode") == "verify"
             and independent.get("success") is True
             and _same(independent.get("binding"), {"request_sha256": request_ref["sha256"],
                                                     "launch_sha256": launch_ref["sha256"]})
             and independent.get("network_guard", {}).get("socket_denial_verified") is True
             and all(independent.get("guards", {}).get(key) is True
                     for key in ("source_before", "source_after", "inputs_after")),
             "supervised verifier binding or guards differ")
    fields = {"schema", "passed", "mode", "base_artifact", "final_artifact", "base_version_id",
        "base_format", "final_format", "patch_ref", "receipt_ref", "provenance", "capture_report",
        "replay_report", "checks", "canonical_native_checkpoint", "regenerated_compact_checkpoint",
        "metric_state_identity", "tree_pin", "timings", "full_checkpoint_authoritative",
        "registered_base_authority_verified", "legacy_raw_bytes_reproduction_required",
        "intermediate_mutations_replayed", "optimizer_acceptance_asserted", "admitted", "promoted",
        "publication_performed"}
    _require(type(value) is dict and set(value) == fields and value["schema"] == SCHEMA,
             "invalid closed shadow receipt")
    _require(value["passed"] is True and value["mode"] == "diagnostic_only"
             and value["full_checkpoint_authoritative"] is True,
             "shadow did not complete diagnostic verification")
    for name in ("registered_base_authority_verified", "legacy_raw_bytes_reproduction_required",
                 "intermediate_mutations_replayed", "optimizer_acceptance_asserted", "admitted",
                 "promoted", "publication_performed"):
        _require(value[name] is False, "unsupported authority claim: " + name)
    checks = {"all_native_components_exact", "canonical_native_state_exact", "metric_lineage_identity_exact",
              "revision_exact", "patch_endpoint_binding_exact", "independent_base_reload",
              "source_artifacts_unchanged", "published_patch_bytes_exact", "compact_final_bytes_exact"}
    _require(type(value["checks"]) is dict and set(value["checks"]) == checks
             and all(flag is True for flag in value["checks"].values()), "complete replay checks missing")
    _require(_same(value["base_artifact"], request["base_artifact"])
             and _same(value["final_artifact"], candidate)
             and value["base_version_id"] == request["base_version_id"], "checkpoint endpoint binding differs")
    _require(value["base_format"] in {"json", "compact"} and value["final_format"] == "compact"
             and _same(value["regenerated_compact_checkpoint"], _content(candidate)),
             "full compact checkpoint byte comparison differs")
    reference(value["canonical_native_checkpoint"], MAX_CHECKPOINT_BYTES)
    expected_provenance = {"schema": SCHEMA, "capture_kind": "complete_checkpoint_endpoint_difference",
        "base_artifact": _content(request["base_artifact"]), "final_artifact": _content(candidate),
        "context": shadow_provenance(request_ref=request_ref,
            launch_ref=launch_ref, native_result_ref=native_result_ref),
        "optimizer_acceptance_asserted": False, "registered_base_authority_verified": False}
    _require(_same(value["provenance"], expected_provenance), "request/launch provenance differs")
    capture = value["capture_report"]
    _require(type(capture) is dict and capture.get("profile") == PROFILE
             and capture.get("scope") == "endpoint_shadow_only" and capture.get("admitted") is False,
             "capture scope differs")
    names = list(MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS)
    _snapshot(capture["base_snapshot"], request["base_identity"], names)
    _snapshot(capture["result_snapshot"], independent["state_identity"], names)
    _require(_same(value["metric_state_identity"], independent["metric_state_identity"]),
             "metric identity differs from full verifier")
    output = safe_path(attempt) / "sparse-shadow"
    refs = []
    for name, filename, limit in (("patch_ref", "patch.json", MAX_PATCH_BYTES),
                                  ("receipt_ref", "receipt.json", MAX_RESULT_BYTES)):
        ref = reference(value[name], limit, with_path=True)
        _require(ref["path"] == str(output / filename), "artifact escaped shadow output directory")
        refs.append(ref)
    patch_ref, receipt_ref = refs
    persisted = parse_json(verify(receipt_ref))
    _require(_same(persisted, {key: item for key, item in value.items() if key != "receipt_ref"}),
             "persisted and observed shadow receipts differ")
    segment = decode_patch(verify(patch_ref, MAX_PATCH_BYTES))
    _require(_same(_content(patch_ref), {"sha256": capture["patch_sha256"], "bytes": capture["patch_bytes"]})
             and _same(segment.provenance, expected_provenance), "patch content/provenance differs")
    patch = segment.patch
    _require(segment.base_version_id == request["base_version_id"] and segment.sequence == 0
             and segment.base_state_identity == request["base_identity"]["digest"]
             and segment.result_state_identity == independent["state_identity"]["digest"]
             and patch.base_revision == request["base_identity"]["revision"]
             and patch.result_revision == independent["state_identity"]["revision"],
             "patch identity or revision differs")
    changed = [name for name in names if capture["base_snapshot"]["components"][name]
               != capture["result_snapshot"]["components"][name]]
    revision_only = not changed and patch.base_revision != patch.result_revision
    witness = "architecture_version" if revision_only else None
    counts = {"changed_component_count": len(changed), "touched_row_count": len(patch.rows),
        "touched_component_count": len(patch.components), "inserted_rows": sum(not x.before_exists for x in patch.rows),
        "deleted_rows": sum(not x.after_exists for x in patch.rows), "revision_witness_count": int(revision_only)}
    _require(_same(capture["counts"], counts) and capture["changed_components"] == changed
             and capture["revision_only"] is revision_only and capture["revision_witness_component"] == witness,
             "patch counts or revision witness differ")
    touched = {x.component for x in (*patch.rows, *patch.components)}
    _require(touched == set(changed) | ({witness} if witness else set()),
             "patch does not cover raw changed components")
    row_names = {x.component for x in patch.rows}
    replacements = [x.component for x in patch.components if x.component != witness]
    _require(capture["row_component_names"] == [name for name in names if name in row_names]
             and capture["component_replacements"] == replacements,
             "row/component capture inventory differs")
    replay = value["replay_report"]
    for key, expected in {"base_revision": patch.base_revision, "result_revision": patch.result_revision,
        "base_state_identity": segment.base_state_identity, "result_state_identity": segment.result_state_identity,
        "payload_sha256": segment.payload_sha256, "sequence": 0,
        "touched_row_count": len(patch.rows), "touched_component_count": len(patch.components), "admitted": False}.items():
        _require(_same(replay.get(key), expected), "replay result differs: " + key)
    return [("sparse_shadow_patch", patch_ref), ("sparse_shadow_receipt", receipt_ref)]


def independent_request(launch_ref):
    """Read the already owner-verified launch without rebinding its checksum."""
    from .autoencoder_daemon_invocation_contracts import MAX_REQUEST_BYTES
    return parse_json(verify(launch_ref, MAX_REQUEST_BYTES))["request"]
