"""Offline, immutable publication plans for complete source-corpus packages.

A captured catalog version is a declaration, not a live database attestation.
The package is verified and its ordered rows are checked against that version;
this module never opens its former catalog/package paths or contacts the Hub.
"""
from __future__ import annotations

from dataclasses import replace
import json
import re

from ..duckdb_control.source_corpus_binding import SourceCorpusBinding, SourceCorpusBindingError
from ..optimizers.logic_theorem_optimizer import autoencoder_uscode_corpus_export as export
from .publication_profile import HuggingFacePublicationProfile, PublicationProfileError
from .publisher import HuggingFacePublicationError, HuggingFaceReleasePublisher


SCHEMA_VERSION = "source-corpus-hf-release-plan-v1"
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_QUALIFICATION = {
    "package_verified": True, "source_version_binding_verified": True,
    "current_catalog_verified": False, "remote_inventory_checked": False,
    "remote_parent_verified": False, "upload_performed": False,
    "download_performed": False, "admitted": False, "formalized": False,
    "source_authority_authenticated": False, "language_verified": False,
    "training_dispatched": False, "dataset_viewer_verified": False,
}


class SourceCorpusReleaseError(ValueError):
    """The captured source version, package or offline publication plan differs."""


def _require(condition, message):
    if not condition:
        raise SourceCorpusReleaseError(message)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def source_corpus_publication_profile(repository_id):
    """An explicit dataset destination; no default repository or live client."""
    _require(type(repository_id) is str and _REPO.fullmatch(repository_id)
             and ".." not in repository_id, "repository_id must be an explicit namespace/dataset")
    return HuggingFacePublicationProfile(
        profile_id="source-corpus", program_id="federal-law-source-corpus",
        goal_id="source-corpus-delivery",
        plan_schema_version="source-corpus-hf-publication-plan/v1",
        receipt_schema_version="source-corpus-hf-publication-receipt/v1",
        repository_id=repository_id, repository_type="dataset",
        release_prefix_template="data/source_corpus/{release_id}",
        pointer_path="runtime/source-corpus-release-pointer.json",
        canonical_release_schema=export.SCHEMA_VERSION,
        commit_message="source-corpus: append immutable source and provenance files",
    )


def plan_source_corpus_release(version, package_directory, *, repository_id,
                               audited_parent_commit=""):
    """Verify package/version binding and plan every immutable file, offline.

    Relocated packages are supported. No catalog is opened, no original path is
    read, and neither a Hub upload nor a Dataset Viewer installation is implied.
    The returned ordinary-JSON report contains no private local package path.
    """
    try:
        profile = source_corpus_publication_profile(repository_id)
        _require(type(audited_parent_commit) is str and
                 (audited_parent_commit == "" or re.fullmatch(r"[0-9a-f]{40}", audited_parent_commit)),
                 "invalid declared audited parent commit")
        with SourceCorpusBinding(version, package_directory) as binding:
            captured, ref = binding.source_version, binding.manifest_artifact
            entries = [{"relative_path": item["relative_path"], "sha256": item["sha256"],
                        "size_bytes": item["bytes"]} for item in binding.file_descriptors]
            publisher = HuggingFaceReleasePublisher(profile=profile, api=None)
            plan = publisher.plan_dry_run({"schema_version": export.SCHEMA_VERSION,
                "release_id": captured["version_id"], "release_sha256": ref["sha256"], "files": entries},
                local_root=binding.package_root, audited_parent_commit=audited_parent_commit)
            plan = replace(plan, metadata={**plan.metadata,
                "source_version": captured,
                "source_export_manifest_included": True,
                "source_scope": "complete_declared_uscode_corpus_family",
                "dataset_config": "corpus", "physical_dataset_split": "corpus",
                "source_partition_column": "split",
                "root_dataset_card_publication": "separate_reviewed_bootstrap_or_cas_required",
                "cost_rates_status": "publisher_defaults_are_illustrative_not_a_huggingface_quote",
                **_QUALIFICATION})
            expected = [{"relative_path": item["relative_path"],
                         "remote_path": plan.release_prefix + "/" + item["relative_path"],
                         "sha256": item["sha256"], "size_bytes": item["size_bytes"],
                         "operation": "add"} for item in entries]
            _require(_json([item.to_dict() for item in plan.operations]) == _json(expected)
                     and not plan.skipped_exact_matches and not plan.existing_remote_paths,
                     "publication plan does not contain the exact complete source package")
            total = binding.total_bytes
            _require(plan.cost_receipt["upload_bytes"] == total, "publication byte total differs")
            # Generic planning alone does not reject absent local files. The
            # shared binding requires exact current bytes after planning too.
            binding.verify_current()
            return {"schema_version": SCHEMA_VERSION, "source_version": captured,
                    "profile": profile.to_dict(), "publication_plan": plan.to_dict(),
                    "file_count": binding.file_count, "total_bytes": total,
                    "qualification": dict(_QUALIFICATION)}
    except (SourceCorpusBindingError, export.CorpusExportError,
            HuggingFacePublicationError, PublicationProfileError, OSError,
            TypeError, UnicodeError) as exc:
        raise SourceCorpusReleaseError(str(exc)) from exc
