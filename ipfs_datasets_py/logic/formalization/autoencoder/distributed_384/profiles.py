"""Pinned four-domain structured heads and honest native projection coverage.

The published heads learned authored composition controls, not the external
corpora listed as candidate data sources. A supported projection checks a typed
declaration; it is neither a source-meaning proof nor a Lake build receipt.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import tempfile

from .contracts import DOMAINS, MAX_BYTES, digest, require

_RELEASE = "releases/20261001-structured-native-v3-experimental"
_SOURCE_REVISION = "2d93857e78ceedc7f055637c887afeaa40653993"
# Copies of the verified release descriptors, independent of documentation files.
_PINS = {
    "intent_ir": (
        "809155ad4d34d67fadca2bef68ee74079bcc3074",
        "22680844b7f1e211580ba9f482cb3a8ec70e6831d06e0a0035e815c95243f8b6",
        "6977665f7ba896a74c78817a8ae3c0dc092b3fc21c8b231268fa1e17a3d157f6"),
    "security_ir": (
        "e451ce831c4fbc9079b7516e5d415dbab9e219ae",
        "8960a22ec1a4c3ff4f900cc6393b9c88d9601a048e3a32a5aa04bf1615c62193",
        "be2ec82a1d2a71171d86c3ffee3f9023a884df13302c33879b38f401f34ff843"),
    "ui_ux_ir": (
        "f817ee062d122e18e8608783dfb2c5e8056d9b78",
        "ea3d9ea74e9e44e36f95ce88cd4753c2d5010b79ced12615f9781adbf8d71800",
        "413f2ec38958665a3e48bdcfaccb780ea17ca449cb5f4516b6908c47e297c4b3"),
    "legal_ir": (
        "249b2267b0115743320822af069de58790528e29",
        "83a89d38af2af3085cdbc34364ac68b3dd79cc88f7b663ea158af91a23afb7ee",
        "c8e42b07f5a6a5374e96d2e2334fb5daf7a2c66ad8d0eccaf06e990425424e08"),
}
_CORPORA = {
    "intent_ir": [dict(repository_id="Publicus/skillcenter-ir",
        role="candidate_source_corpus", typed_export_required=True,
        adapter="ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_training",
        requirements="Pin the export and preserve source groups; source spans alone are not reviewed IntentIR targets.")],
    "security_ir": [dict(repository_id="Publicus/cvefixes-security-ir-graphrag",
        role="candidate_source_corpus", typed_export_required=True,
        adapter="ipfs_datasets_py.logic.formalization.autoencoder.security.security_cve_corpus",
        requirements="Require exact CodeUnit bodies and hashes, typed targets and repository-family splits; CVE labels are not program proofs.")],
    "legal_ir": [dict(repository_id="justicedao/uscode-autoformal-span-cache",
        role="candidate_source_corpus", typed_export_required=True,
        adapter="ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_formula_codec",
        requirements="Pin paired source and canonical rule exports; separate weak supervision from reviewed targets.")],
    "ui_ux_ir": [dict(repository_id=None,
        role="explicit_native_export_required", typed_export_required=True,
        adapter="ipfs_datasets_py.logic.formalization.autoencoder.ui_training_inputs",
        requirements="Supply a reviewed ui-bound-training-row/v1 export with DOM/ARIA, tool preimages and declared behavior; no canonical Hub corpus is selected.")],
}
_AUTHORITY = dict(proof_authority=False, source_semantics_verified=False,
    execution_authority=False, lake_build_executed=False)


def get_profile(domain_id):
    """Return immutable release pins and available routes, never fake coverage."""
    require(type(domain_id) is str and domain_id in DOMAINS, "supported IR domain required")
    from .....optimizers.logic_theorem_optimizer.domain_family_complete_training import native_family_ids
    from ..family_training_v2 import family_training_catalog_v2
    revision, manifest, checkpoint = _PINS[domain_id]
    descriptor = dict(schema="structured-ir-experimental-descriptor/v1",
        domain_id=domain_id, repository_id="Publicus/" + domain_id.replace("_", "-") + "-autoencoder",
        revision=revision, release_prefix=_RELEASE, profile="structured_native_v3",
        manifest_sha256=manifest, checkpoint_sha256=checkpoint,
        source_revision=_SOURCE_REVISION, cold_download_verified=True,
        numerical_replay_matches=True, offline_reload_verified=True, proof_authority=False)
    families = list(native_family_ids(domain_id))
    return dict(schema="distributed-384-domain-profile/v1", domain_id=domain_id,
        dimension=384, checkpoint_descriptor=descriptor,
        native_family_ids=families, default_required_families=list(families),
        family_inventory=deepcopy(family_training_catalog_v2(domain_id)["family_inventory"]),
        parent_training_data=dict(role="authored_control", schema="authored-source-native-composition/v3",
            real_world_corpus=False, source_revision=_SOURCE_REVISION,
            source_path="tests/fixtures/logic/source_reconstruction_v3.py"),
        candidate_training_sources=deepcopy(_CORPORA[domain_id]),
        missing_family_policy="blocks_projection_qualification_not_valid_typed_training",
        qualification_scope="typed_projection_only", **_AUTHORITY)


def _checked_bytes(path, expected_sha256, *, allow_symlink=False):
    path = Path(path)
    require(path.is_file() and (allow_symlink or not path.is_symlink())
        and 0 < path.stat().st_size <= MAX_BYTES, "bounded regular checkpoint artifact required")
    raw = path.read_bytes()
    require(0 < len(raw) <= MAX_BYTES and hashlib.sha256(raw).hexdigest() == expected_sha256,
        "checkpoint artifact SHA256 differs")
    return raw


def load_parent(domain, *, local_path=None, cache_dir=None, local_files_only=False):
    """Load exact published bytes and runtime pins, returning a regular file.

    A supplied local file never performs network access. Hub snapshot symlinks
    are read as input only and copied to immutable content-addressed files.
    """
    from ..structured_source_384 import load_checkpoint
    require(type(local_files_only) is bool, "boolean local_files_only required")
    pin = get_profile(domain)["checkpoint_descriptor"]
    if local_path is not None:
        path = Path(local_path)
        _checked_bytes(path, pin["checkpoint_sha256"])
    else:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.constants import HF_HUB_CACHE
        def download(name):
            return Path(hf_hub_download(repo_id=pin["repository_id"],
                filename=pin["release_prefix"] + "/" + name, revision=pin["revision"],
                repo_type="model", cache_dir=cache_dir, local_files_only=local_files_only))
        _checked_bytes(download("manifest.json"), pin["manifest_sha256"], allow_symlink=True)
        raw = _checked_bytes(download("checkpoint.json"), pin["checkpoint_sha256"], allow_symlink=True)
        directory = Path(cache_dir or HF_HUB_CACHE) / "ipfs-datasets-structured-384"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (pin["checkpoint_sha256"] + ".json")
        if not path.exists() and not path.is_symlink():
            fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    pass  # Concurrent materialization must have the same bytes.
            finally:
                os.unlink(temporary)
        _checked_bytes(path, pin["checkpoint_sha256"])
    load_checkpoint(path, expected_sha256=pin["checkpoint_sha256"], expected_domain=domain)
    return path.resolve()


def project_candidate(domain, target, source_text, required_families=None):
    """Project the supplied candidate without replacing it or inventing context.

    Supported means at least one complete native projection in the reported
    scope. It does not claim every target facet is represented, source fidelity,
    theorem proving, or external syntax-checker execution. Full-family policies
    stay blocked when this target contains only a small native fragment.
    """
    from ..source_training_v2 import validate_target
    profile = get_profile(domain)
    require(type(source_text) is str and source_text.strip()
        and len(source_text.encode()) <= 1048576, "bounded nonempty source text required")
    selected = profile["default_required_families"] if required_families is None else required_families
    known = {row["family_id"] for row in profile["family_inventory"]}
    require(type(selected) in (list, tuple) and bool(selected)
        and all(type(f) is str and f in known for f in selected)
        and len(set(selected)) == len(selected), "unique nonempty canonical family selection required")
    selected = sorted(selected)
    inventory = {row["family_id"]: row for row in profile["family_inventory"]}
    families = {family: dict(family_id=family, status="missing_context",
        reason=inventory[family]["frontier"], requires=inventory[family]["requires"], projections=[])
        for family in selected}
    report = dict(schema="distributed-384-candidate-projections/v1", domain_id=domain,
        candidate_valid=False, candidate_sha256=None,
        source_sha256=hashlib.sha256(source_text.encode()).hexdigest(), requested_families=selected,
        qualification_scope="typed_projection_only", target_rewritten=False,
        continue_training_if_target_valid=True, **_AUTHORITY)

    def finish():
        result = dict(report, families=list(families.values()),
            all_required_families_supported=all(row["status"] == "supported" for row in families.values()))
        result["report_sha256"] = digest(result)
        return result

    def failure(status, reason):
        for row in families.values():
            row.update(status=status, reason=reason, projections=[])

    try:
        validated = validate_target(domain, target)
        if domain == "ui_ux_ir":
            from ..ui_source_contract_384 import validate_training_target
            validate_training_target(target)
        report.update(candidate_valid=True, candidate_sha256=digest(target))
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        failure("failed", "invalid_native_target:" + str(error)[:512])
        return finish()

    try:
        if domain in {"intent_ir", "legal_ir"}:
            from ..family_training_v2 import prepare_family_training_targets_v2
            if domain == "intent_ir":
                if validated["kind"] == "intent_rich_ast":
                    from ....intent_ir.formalize.rich_grammar import parse_instruction
                    native = validated["native_ir"]
                    try:
                        parsed = parse_instruction(source_text)
                    except ValueError:
                        failure("missing_context", "source_outside_bounded_intent_grammar")
                        return finish()
                    if parsed != native:
                        failure("failed", "intent_candidate_differs_from_exact_source")
                        return finish()
                else:
                    from ....intent_ir.decoder import decode_intent_ir
                    native = decode_intent_ir(validated["native_ir"])
                    if any(source.content_sha256 != report["source_sha256"] for source in native.sources):
                        failure("failed", "intent_native_source_hash_differs")
                        return finish()
            else:
                from ....legal_ir.canonical_contracts import CanonicalRoundTripIR
                native = CanonicalRoundTripIR.from_dict(validated["canonical_ir"])
            projected = prepare_family_training_targets_v2(domain, document=native,
                source_text=source_text, requested_families=selected)
            report["native_report_sha256"] = projected["report_sha256"]
            for family, row in families.items():
                values = [p for p in projected["projections"] if p["logic_family"] == family]
                # Partial projections cannot satisfy a required family.
                ready = [p for p in values if p["ready_for_training"]
                    and "partial_native_projection" not in p["qualification_gaps"]]
                if ready:
                    row.update(status="supported", reason="native_typed_projection_executed", projections=ready)
                elif values:
                    row.update(status="failed" if any(not p["ready_for_training"] for p in values)
                        else "missing_context", reason="native_projection_not_complete", projections=values)
        elif domain == "security_ir":
            if validated["kind"] != "program_expression":
                failure("missing_context", "security_document_requires_exact_CodeUnit_and_native_model_evidence")
                return finish()
            from ..security.source_program_binding_384_v2 import qualify_source_candidate
            projected = qualify_source_candidate(source_text, target)
            report["source_qualification"] = projected
            if projected["status"] == "qualified" and "program" in families:
                families["program"].update(status="supported", reason="exact_source_program_binding_checked",
                    projections=projected["projections"])
            elif projected["status"] != "qualified":
                failure("failed" if projected["status"] == "mismatch" else "missing_context", projected["reason"])
        else:
            from ..ui_source_contract_384 import qualify_source_candidate
            projected = qualify_source_candidate(source_text, target)
            report["source_qualification"] = projected
            if projected["status"] == "projected_candidate" and "frame_logic" in families:
                values = projected["projections"]
                # This compiler lists fixed capability exclusions even when a
                # component declares none of them. Its actual supported scope
                # is identity/role/relationship facts; retain every exclusion.
                complete = bool(values) and all(p.get("facts") for p in values)
                families["frame_logic"].update(status="supported" if complete else "missing_context",
                    reason=projected["projection_scope"], projections=values,
                    coverage_scope=projected["projection_scope"],
                    unprojected_facets=projected["unprojected_facets"],
                    complete_target_semantics=False)
            elif projected["status"] != "projected_candidate":
                failure("failed" if projected["status"] == "invalid" else "missing_context", projected["reason"])
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        failure("failed", "native_projection_error:" + str(error)[:512])
    return finish()


__all__ = ["get_profile", "load_parent", "project_candidate"]
