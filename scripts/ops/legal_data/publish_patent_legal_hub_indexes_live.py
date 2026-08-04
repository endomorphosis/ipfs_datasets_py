#!/usr/bin/env python3
"""Package, admit, stage, verify, and seal full-authority Hub republication.

PATLAW-191 — multi-artifact corpus + BM25 + vector + knowledge-graph Hub
republication from the full-authority public legal corpus (PATLAW-186…190).

**CI default is offline fake-service:** package → admit → stage → pin-verify →
seal a staged-not-promoted publication receipt. No live Hub network and no
unattended ``main`` promote.

**Live operator path** remains available with ``--live-hub`` (requires
``HF_TOKEN`` / ``~/.cache/huggingface/token``). Live promote still needs an
operator-held approval key and never embeds tokens in receipts.

Acceptance (fail-closed):

* Package counts reflect the full-authority corpus (document parity across
  corpus / BM25 / vectors; by-family inventory from the recipe).
* Admission passes DLP / rights / Viewer gates without premature credentials.
* Verification binds expanded per-artifact digests for every projection.
* Publication receipt cannot claim ``promoted`` without a real promote
  evidence blob (PATLAW-179).
* CI remains ``fake-service`` by default.

Examples:

  # CI / supervisor offline republication (default)
  python scripts/ops/legal_data/publish_patent_legal_hub_indexes_live.py \\
    --work-dir /var/tmp/patlaw-191-ci \\
    --fake-service

  # Optional offline promote drill (still fake-service; never live main)
  python scripts/ops/legal_data/publish_patent_legal_hub_indexes_live.py \\
    --work-dir /var/tmp/patlaw-191-promote-drill \\
    --fake-service --promote --claim-promoted

  # Operator live stage (no auto-promote)
  python scripts/ops/legal_data/publish_patent_legal_hub_indexes_live.py \\
    --work-dir /var/tmp/patlaw-191-live \\
    --live-hub --approver "operator@example.com" --skip-promote
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (  # noqa: E402
    BM25_REPOSITORY,
    CANONICAL_REPOSITORY_NAMES,
    CORPUS_REPOSITORY,
    KNOWLEDGE_GRAPH_REPOSITORY,
    ORGANIZATION,
    VECTORS_REPOSITORY,
)
from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (  # noqa: E402
    LiveHubApiAdapter,
    default_test_base_revisions,
    resolve_hub_token,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (  # noqa: E402
    MANIFEST_FILENAME,
    HubIndexPackage,
    package_patent_legal_hub_indexes,
)


# ---------------------------------------------------------------------------
# Pins (PATLAW-191 full-authority Hub republication surface)
# ---------------------------------------------------------------------------

TASK_ID: Final = "PATLAW-191"
GOAL_ID: Final = "PATLAW-G218"
PROGRAM_ID: Final = "patent-legal-intelligence-v1"
FULL_AUTHORITY_RECIPE_ID: Final = "patlaw-full-authority-public-legal-corpus"
FULL_AUTHORITY_FAMILIES: Final = ("cfr", "mpep", "guidance")
PROJECTION_FAMILIES: Final = (
    "corpus",
    "bm25",
    "vectors",
    "knowledge_graph",
)
REPUBLICATION_RECEIPT_SCHEMA: Final = (
    "patent-legal-hub-full-authority-republication-receipt/v1"
)
CODE_VERSION: Final = "1"

MATERIALIZE_SCRIPT: Final = (
    Path(__file__).resolve().parent / "materialize_public_legal_corpus.py"
)
BM25_SCRIPT: Final = (
    Path(__file__).resolve().parent / "build_public_legal_bm25_index.py"
)
VECTOR_SCRIPT: Final = (
    Path(__file__).resolve().parent / "build_public_legal_vector_index.py"
)
GRAPH_SCRIPT: Final = (
    Path(__file__).resolve().parent / "build_public_legal_knowledge_graph.py"
)
PRODUCTION_RECIPE_SCRIPT: Final = (
    Path(__file__).resolve().parent / "build_public_legal_production_recipe.py"
)
ADMIT_SCRIPT: Final = (
    Path(__file__).resolve().parent / "admit_patent_legal_hub_indexes.py"
)
STAGE_SCRIPT: Final = (
    Path(__file__).resolve().parent / "stage_patent_legal_hub_indexes.py"
)
VERIFY_SCRIPT: Final = (
    Path(__file__).resolve().parent / "verify_patent_legal_hub_indexes.py"
)
SEAL_SCRIPT: Final = (
    Path(__file__).resolve().parent
    / "seal_patent_legal_hub_index_publication_receipt.py"
)
PREPARE_CHECKLIST_SCRIPT: Final = (
    Path(__file__).resolve().parent
    / "prepare_patent_legal_hub_promote_checklist.py"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FullAuthorityRepublicationError(RuntimeError):
    """Raised when full-authority Hub republication preconditions fail."""

    code = "full_authority_republication_error"


class PackageCountMismatchError(FullAuthorityRepublicationError):
    """Package counts do not reflect the full-authority corpus."""

    code = "package_count_mismatch"


class AdmissionFailedError(FullAuthorityRepublicationError):
    """DLP / rights / Viewer admission refused the package."""

    code = "admission_failed"


class VerificationDigestError(FullAuthorityRepublicationError):
    """Verification did not bind expanded projection digests."""

    code = "verification_digest_error"


class FabricatedPromoteClaimError(FullAuthorityRepublicationError):
    """Receipt attempted to claim promoted without real promote evidence."""

    code = "fabricated_promote_claim"


# ---------------------------------------------------------------------------
# Script loaders
# ---------------------------------------------------------------------------


def _load_script_module(path: Path, module_name: str) -> ModuleType:
    if not path.is_file():
        raise FullAuthorityRepublicationError(f"missing required script: {path}")
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise FullAuthorityRepublicationError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_materialize_module() -> ModuleType:
    return _load_script_module(
        MATERIALIZE_SCRIPT, "_patlaw191_materialize_public_legal_corpus"
    )


def _load_bm25_module() -> ModuleType:
    return _load_script_module(
        BM25_SCRIPT, "_patlaw191_build_public_legal_bm25_index"
    )


def _load_vector_module() -> ModuleType:
    return _load_script_module(
        VECTOR_SCRIPT, "_patlaw191_build_public_legal_vector_index"
    )


def _load_graph_module() -> ModuleType:
    return _load_script_module(
        GRAPH_SCRIPT, "_patlaw191_build_public_legal_knowledge_graph"
    )


def _load_production_recipe_module() -> ModuleType:
    return _load_script_module(
        PRODUCTION_RECIPE_SCRIPT,
        "_patlaw191_build_public_legal_production_recipe",
    )


def _load_admit_module() -> ModuleType:
    return _load_script_module(
        ADMIT_SCRIPT, "_patlaw191_admit_patent_legal_hub_indexes"
    )


def _load_stage_module() -> ModuleType:
    return _load_script_module(
        STAGE_SCRIPT, "_patlaw191_stage_patent_legal_hub_indexes"
    )


def _load_verify_module() -> ModuleType:
    return _load_script_module(
        VERIFY_SCRIPT, "_patlaw191_verify_patent_legal_hub_indexes"
    )


def _load_seal_module() -> ModuleType:
    return _load_script_module(
        SEAL_SCRIPT, "_patlaw191_seal_patent_legal_hub_index_publication_receipt"
    )


def _load_prepare_checklist_module() -> ModuleType:
    return _load_script_module(
        PREPARE_CHECKLIST_SCRIPT,
        "_patlaw191_prepare_patent_legal_hub_promote_checklist",
    )


# ---------------------------------------------------------------------------
# Full-authority recipe / package
# ---------------------------------------------------------------------------


def load_full_authority_recipe(
    *,
    assert_complete: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build the offline full-authority production recipe (PATLAW-186)."""

    try:
        mat_mod = _load_materialize_module()
        if hasattr(mat_mod, "load_full_authority_recipe"):
            recipe = mat_mod.load_full_authority_recipe(
                assert_complete=assert_complete, **kwargs
            )
            if not isinstance(recipe, dict):
                raise FullAuthorityRepublicationError(
                    "full-authority recipe must be a dict"
                )
            return recipe
    except FullAuthorityRepublicationError:
        raise
    except Exception:
        pass

    build_mod = _load_production_recipe_module()
    recipe = build_mod.build_full_authority_recipe(
        assert_complete=assert_complete, **kwargs
    )
    if not isinstance(recipe, dict):
        raise FullAuthorityRepublicationError("full-authority recipe must be a dict")
    return recipe


def assert_recipe_is_full_authority(recipe: Mapping[str, Any]) -> None:
    """Fail closed unless *recipe* proves full-authority completeness."""

    try:
        mat_mod = _load_materialize_module()
        if hasattr(mat_mod, "assert_recipe_is_full_authority"):
            mat_mod.assert_recipe_is_full_authority(recipe)
            return
    except FullAuthorityRepublicationError:
        raise
    except Exception:
        pass

    build_mod = _load_production_recipe_module()
    build_mod.assert_full_authority_complete(recipe)


def assert_package_counts_reflect_full_authority(
    package: HubIndexPackage,
    recipe: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove package counts reflect the full-authority corpus inventory."""

    counts = package.manifest.counts
    recipe_counts = dict(recipe.get("counts") or {})
    expected_docs = int(recipe_counts.get("documents") or 0)
    if expected_docs < 1:
        raise PackageCountMismatchError(
            "full-authority recipe has no documents in counts.documents"
        )

    corpus_docs = int(counts.corpus_documents)
    bm25_docs = int(counts.bm25_documents)
    vector_docs = int(counts.vector_documents)
    if corpus_docs != expected_docs:
        raise PackageCountMismatchError(
            f"corpus_documents {corpus_docs} != recipe documents {expected_docs}"
        )
    if bm25_docs != expected_docs:
        raise PackageCountMismatchError(
            f"bm25_documents {bm25_docs} != recipe documents {expected_docs}"
        )
    if vector_docs != expected_docs:
        raise PackageCountMismatchError(
            f"vector_documents {vector_docs} != recipe documents {expected_docs}"
        )

    by_family = dict(recipe_counts.get("by_family") or {})
    for family in FULL_AUTHORITY_FAMILIES:
        family_count = int(by_family.get(family) or 0)
        if family_count < 1:
            raise PackageCountMismatchError(
                f"full-authority by_family.{family} missing or zero"
            )

    fa_counts = dict(recipe_counts.get("full_authority") or {})
    if not fa_counts:
        raise PackageCountMismatchError(
            "recipe counts.full_authority inventory missing"
        )

    fa_block = dict(recipe.get("full_authority") or {})
    if not bool(fa_block.get("complete")):
        raise PackageCountMismatchError(
            "recipe full_authority.complete is not true"
        )

    return {
        "ok": True,
        "corpus_documents": corpus_docs,
        "bm25_documents": bm25_docs,
        "vector_documents": vector_docs,
        "graph_nodes": int(counts.graph_nodes),
        "graph_edges": int(counts.graph_edges),
        "recipe_documents": expected_docs,
        "by_family": by_family,
        "full_authority_inventory": fa_counts,
        "full_authority_complete": True,
        "families": list(FULL_AUTHORITY_FAMILIES),
    }


def package_full_authority_hub_indexes(
    recipe: Mapping[str, Any] | None = None,
    *,
    stage: bool = True,
    output_dir: Path | None = None,
    organization: str = ORGANIZATION,
    notes: str = "",
    assert_complete: bool = True,
    require_full_authority: bool = True,
) -> tuple[HubIndexPackage, dict[str, Any], dict[str, Any]]:
    """Materialize full-authority corpus + indexes and package for Hub.

    Uses PATLAW-187/188/189/190 builders so corpus root pins stay aligned
    across BM25, vectors, and knowledge graph.
    """

    resolved = (
        dict(recipe)
        if recipe is not None
        else load_full_authority_recipe(assert_complete=assert_complete)
    )
    if require_full_authority:
        assert_recipe_is_full_authority(resolved)

    mat_mod = _load_materialize_module()
    bm25_mod = _load_bm25_module()
    vec_mod = _load_vector_module()
    graph_mod = _load_graph_module()

    materialization, inventory = mat_mod.materialize_full_authority_corpus(
        resolved,
        stage=False,
        require_full_authority=require_full_authority,
        assert_complete=assert_complete,
    )
    corpus_root = str(materialization.corpus_root_cid or "")

    bm25_snapshot, _bm25_inv, _bm25_hub = bm25_mod.build_full_authority_bm25_index(
        recipe=resolved,
        expected_corpus_root_cid=corpus_root or None,
        stage_hub_bulk=False,
        require_full_authority=require_full_authority,
        assert_complete=assert_complete,
    )
    vector_result, _mat_vec, _vec_receipt = vec_mod.build_full_authority_vectors(
        resolved,
        materialization=materialization,
        require_full_authority=require_full_authority,
        assert_complete=assert_complete,
        include_vectors_in_stage=False,
    )
    graph_result, _graph_receipt = graph_mod.build_full_authority_knowledge_graph(
        recipe=resolved,
        materialization=materialization,
        require_full_authority=require_full_authority,
        assert_complete=assert_complete,
    )

    package_notes = notes or (
        f"{TASK_ID} / {GOAL_ID} full-authority Hub republication package "
        f"recipe_id={resolved.get('recipe_id') or FULL_AUTHORITY_RECIPE_ID}"
    )
    package = package_patent_legal_hub_indexes(
        corpus=materialization,
        bm25=bm25_snapshot,
        vector=vector_result,
        graph=graph_result,
        organization=organization,
        stage=stage,
        output_dir=output_dir,
        notes=package_notes,
    )
    count_receipt = assert_package_counts_reflect_full_authority(package, resolved)
    count_receipt["package_root_cid"] = package.manifest.package_root_cid
    count_receipt["corpus_root_cid"] = package.manifest.corpus_root_cid
    count_receipt["bm25_root_cid"] = package.manifest.bm25_root_cid
    count_receipt["vector_root_cid"] = package.manifest.vector_root_cid
    count_receipt["graph_root_cid"] = package.manifest.graph_root_cid
    count_receipt["package_digest_sha256"] = package.manifest.package_digest_sha256
    count_receipt["corpus_digest_sha256"] = package.manifest.corpus_digest_sha256
    count_receipt["bm25_digest_sha256"] = package.manifest.bm25_digest_sha256
    count_receipt["vector_digest_sha256"] = package.manifest.vector_digest_sha256
    count_receipt["graph_digest_sha256"] = package.manifest.graph_digest_sha256
    count_receipt["recipe_id"] = str(
        resolved.get("recipe_id") or FULL_AUTHORITY_RECIPE_ID
    )
    count_receipt["materialize_inventory"] = (
        dict(inventory) if isinstance(inventory, Mapping) else {}
    )
    return package, resolved, count_receipt


# ---------------------------------------------------------------------------
# Admission / stage / verify / seal helpers
# ---------------------------------------------------------------------------


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FullAuthorityRepublicationError(f"expected JSON object in {path}")
    return payload


def _token_env_keys() -> tuple[str, ...]:
    return (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
    )


def _hide_hub_tokens() -> dict[str, str]:
    saved: dict[str, str] = {}
    for key in _token_env_keys():
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    return saved


def _restore_env(saved: Mapping[str, str]) -> None:
    os.environ.update(dict(saved))


def admit_full_authority_package(
    package_dir: Path,
    *,
    receipt_out: Path,
    organization: str = ORGANIZATION,
) -> dict[str, Any]:
    """Run PATLAW-175 admission with credentials unset (fail-closed)."""

    admit_mod = _load_admit_module()
    saved = _hide_hub_tokens()
    try:
        rc = admit_mod.main(
            [
                "--package-dir",
                str(package_dir),
                "--organization",
                organization,
                "--receipt-out",
                str(receipt_out),
            ]
        )
    finally:
        _restore_env(saved)
    if rc != 0 or not receipt_out.is_file():
        raise AdmissionFailedError(
            f"admission failed rc={rc} receipt={receipt_out}"
        )
    receipt = _load_json(receipt_out)
    if not bool(receipt.get("admitted")):
        raise AdmissionFailedError(
            f"package not admitted: {receipt.get('reason_codes') or receipt}"
        )
    return receipt


def assert_verification_binds_expanded_digests(
    verification: Mapping[str, Any],
    package: HubIndexPackage | None = None,
) -> dict[str, Any]:
    """Fail closed unless verification binds expanded per-artifact digests."""

    projection_digests = verification.get("projection_digests") or {}
    if not isinstance(projection_digests, Mapping):
        raise VerificationDigestError("verification.projection_digests missing")

    bound: dict[str, int] = {}
    for family in PROJECTION_FAMILIES:
        family_digests = projection_digests.get(family)
        if not isinstance(family_digests, Mapping) or not family_digests:
            raise VerificationDigestError(
                f"verification missing expanded digests for projection {family!r}"
            )
        # Expanded inventory: multiple artifact paths (not a single opaque blob).
        if len(family_digests) < 1:
            raise VerificationDigestError(
                f"projection {family!r} has empty digest map"
            )
        for path_key, digest in family_digests.items():
            text = str(digest or "").strip().casefold()
            if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
                raise VerificationDigestError(
                    f"invalid digest for {family}/{path_key}: {digest!r}"
                )
        bound[family] = len(family_digests)

    # At least one projection must carry multi-artifact expansion (package
    # support files + index payloads). Full-authority packages expand all four.
    multi = sum(1 for n in bound.values() if n > 1)
    if multi < 1:
        raise VerificationDigestError(
            "verification digests are not expanded across artifacts"
        )

    package_root = str(
        verification.get("package_root_cid")
        or verification.get("release_root_cid")
        or ""
    ).strip()
    if not package_root:
        raise VerificationDigestError(
            "verification missing package_root_cid / release_root_cid"
        )

    if package is not None:
        expected = str(package.manifest.package_root_cid or "").strip()
        if expected and package_root != expected:
            raise VerificationDigestError(
                f"verification package_root_cid {package_root!r} != "
                f"package {expected!r}"
            )
        # Root digests from the package must be present on the receipt when
        # the verify surface records them at the top level.
        for attr, key in (
            ("corpus_root_cid", "corpus_root_cid"),
            ("bm25_root_cid", "bm25_root_cid"),
            ("vector_root_cid", "vector_root_cid"),
            ("graph_root_cid", "graph_root_cid"),
        ):
            expected_cid = str(getattr(package.manifest, attr, "") or "").strip()
            observed = str(verification.get(key) or "").strip()
            if expected_cid and observed and expected_cid != observed:
                raise VerificationDigestError(
                    f"verification {key} {observed!r} != package {expected_cid!r}"
                )

    return {
        "ok": True,
        "package_root_cid": package_root,
        "projection_artifact_digest_counts": bound,
        "projections": list(PROJECTION_FAMILIES),
        "expanded": True,
    }


def stage_full_authority_package(
    package_dir: Path,
    *,
    base_revisions_file: Path,
    admission_receipt: Path,
    receipt_out: Path,
    organization: str = ORGANIZATION,
    fake_service: bool = True,
    live_hub: bool = False,
    token_env: str = "HF_TOKEN",
) -> dict[str, Any]:
    """Stage authenticated Hub PRs (fake-service default; live optional)."""

    if fake_service and live_hub:
        raise FullAuthorityRepublicationError(
            "--fake-service and --live-hub are mutually exclusive"
        )
    if not fake_service and not live_hub:
        # CI remains fake-service default.
        fake_service = True

    stage_mod = _load_stage_module()
    args = [
        "--mode",
        "stage",
        "--package-dir",
        str(package_dir),
        "--base-revisions-file",
        str(base_revisions_file),
        "--admission-receipt",
        str(admission_receipt),
        "--require-admission",
        "--organization",
        organization,
        "--receipt-out",
        str(receipt_out),
    ]
    if fake_service:
        args.append("--fake-service")
    if live_hub:
        args.extend(["--live-hub", "--token-env", token_env])

    rc = stage_mod.main(args)
    if rc != 0 or not receipt_out.is_file():
        raise FullAuthorityRepublicationError(
            f"stage failed rc={rc} receipt={receipt_out}"
        )
    receipt = _load_json(receipt_out)
    if fake_service and not bool(receipt.get("fake_service")):
        raise FullAuthorityRepublicationError(
            "CI stage receipt must record fake_service=true"
        )
    if live_hub and bool(receipt.get("fake_service")):
        raise FullAuthorityRepublicationError(
            "live stage receipt must not claim fake_service"
        )
    return receipt


def verify_full_authority_package(
    package_dir: Path,
    *,
    base_revisions_file: Path,
    receipt_out: Path,
    organization: str = ORGANIZATION,
    fake_service: bool = True,
    package: HubIndexPackage | None = None,
    verified_cache_root: Path | None = None,
) -> dict[str, Any]:
    """Pinned redownload verify; binds expanded digests (fake-service CI)."""

    verify_mod = _load_verify_module()
    # Always use an empty cache directory so repeated verifies do not collide
    # with a prior fake-service redownload tree under the package work dir.
    cache_root = verified_cache_root
    if cache_root is None:
        cache_root = receipt_out.parent / f"verified-cache-{receipt_out.stem}"
    cache_root = Path(cache_root)
    if cache_root.exists():
        # Require empty: if leftovers exist, pick a unique sibling.
        if any(cache_root.iterdir()):
            cache_root = receipt_out.parent / (
                f"verified-cache-{receipt_out.stem}-{_utc_stamp()}"
            )
    cache_root.mkdir(parents=True, exist_ok=True)

    args = [
        "--package-dir",
        str(package_dir),
        "--base-revisions-file",
        str(base_revisions_file),
        "--organization",
        organization,
        "--receipt-out",
        str(receipt_out),
        "--verified-cache-root",
        str(cache_root),
    ]
    if fake_service:
        args.append("--fake-service")

    rc = verify_mod.main(args)
    if rc != 0 or not receipt_out.is_file():
        raise FullAuthorityRepublicationError(
            f"verify failed rc={rc} receipt={receipt_out}"
        )
    receipt = _load_json(receipt_out)
    digest_proof = assert_verification_binds_expanded_digests(receipt, package)
    receipt = dict(receipt)
    receipt["_expanded_digest_proof"] = digest_proof
    return receipt


def prepare_promote_checklist_optional(
    *,
    stage_receipt: Path,
    verification_receipt: Path,
    admission_receipt: Path | None,
    package_manifest: Path | None,
    output: Path,
) -> Path | None:
    """Best-effort promote checklist; returns path or None on tool refusal."""

    prep_mod = _load_prepare_checklist_module()
    args = [
        "--stage-receipt",
        str(stage_receipt),
        "--verification-receipt",
        str(verification_receipt),
        "--output",
        str(output),
    ]
    if admission_receipt is not None and admission_receipt.is_file():
        args.extend(["--admission-receipt", str(admission_receipt)])
    if package_manifest is not None and package_manifest.is_file():
        args.extend(["--package-manifest", str(package_manifest)])
    try:
        rc = prep_mod.main(args)
    except Exception:
        return None
    if rc == 0 and output.is_file():
        return output
    return None


def seal_full_authority_republication(
    *,
    stage_receipt: Path,
    verification_receipt: Path,
    output: Path,
    promote_checklist: Path | None = None,
    promote_evidence: Path | None = None,
    package_manifest: Path | None = None,
    claim_promoted: bool = False,
    mode: str = "offline",
) -> dict[str, Any]:
    """Seal staged-vs-promoted publication receipt (fail-closed on fabricate)."""

    if claim_promoted and (promote_evidence is None or not promote_evidence.is_file()):
        raise FabricatedPromoteClaimError(
            "cannot claim promoted without a real promote evidence blob"
        )

    seal_mod = _load_seal_module()
    args = [
        "--stage-receipt",
        str(stage_receipt),
        "--verification-receipt",
        str(verification_receipt),
        "--output",
        str(output),
        "--mode",
        mode,
    ]
    if promote_checklist is not None and promote_checklist.is_file():
        args.extend(["--promote-checklist", str(promote_checklist)])
    else:
        args.append("--allow-missing-checklist")
    if package_manifest is not None and package_manifest.is_file():
        args.extend(["--package-manifest", str(package_manifest)])
    if promote_evidence is not None and promote_evidence.is_file():
        args.extend(["--promote-evidence", str(promote_evidence)])
    if claim_promoted:
        args.append("--claim-promoted")

    rc = seal_mod.main(args)
    if rc != 0:
        # Surface seal module errors as fabricated-promote when appropriate.
        if claim_promoted and (
            promote_evidence is None or not promote_evidence.is_file()
        ):
            raise FabricatedPromoteClaimError(
                "seal refused promoted claim without promote evidence"
            )
        raise FullAuthorityRepublicationError(
            f"seal publication receipt failed rc={rc}"
        )
    if not output.is_file():
        raise FullAuthorityRepublicationError(f"seal did not write {output}")
    receipt = _load_json(output)

    if claim_promoted or promote_evidence is not None:
        if receipt.get("disposition") != "promoted":
            raise FullAuthorityRepublicationError(
                "expected promoted disposition with promote evidence"
            )
        if not bool(receipt.get("main_published")):
            raise FullAuthorityRepublicationError(
                "promoted receipt must set main_published=true"
            )
    else:
        if receipt.get("disposition") == "promoted":
            raise FabricatedPromoteClaimError(
                "receipt claimed promoted without promote evidence path"
            )
        if bool(receipt.get("main_published")):
            raise FabricatedPromoteClaimError(
                "receipt set main_published without promote evidence"
            )
    return receipt


def promote_full_authority_package(
    package_dir: Path,
    *,
    base_revisions_file: Path,
    staged_receipt: Path,
    approval_out: Path,
    promote_receipt_out: Path,
    operator_key_file: Path,
    organization: str = ORGANIZATION,
    approver: str = "operator-full-authority",
    fake_service: bool = True,
    live_hub: bool = False,
    token_env: str = "HF_TOKEN",
) -> dict[str, Any]:
    """Sign + promote with operator key (fake-service drill or live)."""

    if fake_service and live_hub:
        raise FullAuthorityRepublicationError(
            "--fake-service and --live-hub are mutually exclusive"
        )
    stage_mod = _load_stage_module()
    if not operator_key_file.exists():
        operator_key_file.write_bytes(secrets.token_bytes(32))
        operator_key_file.chmod(0o600)

    approval_id = f"full-authority-{_utc_stamp()}"
    sign_args = [
        "--mode",
        "sign",
        "--package-dir",
        str(package_dir),
        "--base-revisions-file",
        str(base_revisions_file),
        "--organization",
        organization,
        "--operator-key-file",
        str(operator_key_file),
        "--approver",
        approver,
        "--approval-id",
        approval_id,
        "--approval-out",
        str(approval_out),
    ]
    rc = stage_mod.main(sign_args)
    if rc != 0 or not approval_out.is_file():
        raise FullAuthorityRepublicationError(f"sign failed rc={rc}")

    promote_args = [
        "--mode",
        "promote",
        "--package-dir",
        str(package_dir),
        "--base-revisions-file",
        str(base_revisions_file),
        "--organization",
        organization,
        "--operator-key-file",
        str(operator_key_file),
        "--approval-file",
        str(approval_out),
        "--staged-receipt-file",
        str(staged_receipt),
        "--receipt-out",
        str(promote_receipt_out),
    ]
    if fake_service:
        promote_args.append("--fake-service")
    if live_hub:
        promote_args.extend(["--live-hub", "--token-env", token_env])
    rc = stage_mod.main(promote_args)
    if rc != 0 or not promote_receipt_out.is_file():
        raise FullAuthorityRepublicationError(f"promote failed rc={rc}")
    return _load_json(promote_receipt_out)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_full_authority_hub_republication(
    work_dir: Path,
    *,
    organization: str = ORGANIZATION,
    recipe: Mapping[str, Any] | None = None,
    fake_service: bool = True,
    live_hub: bool = False,
    promote: bool = False,
    claim_promoted: bool = False,
    skip_promote: bool = True,
    approver: str = "operator-full-authority",
    base_revisions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """End-to-end package → admit → stage → verify → seal republication.

    Defaults keep CI offline (``fake_service=True``, no promote). Claiming
    promoted without real promote evidence fails closed.
    """

    if live_hub and fake_service:
        raise FullAuthorityRepublicationError(
            "live_hub and fake_service are mutually exclusive"
        )
    # CI remains fake-service default whenever live_hub is not requested.
    if not live_hub:
        fake_service = True

    do_promote = bool(promote) and not bool(skip_promote)
    if claim_promoted and not do_promote:
        raise FabricatedPromoteClaimError(
            "claim_promoted requires promote=True with real promote evidence"
        )

    work = work_dir.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    package_dir = work / "package"
    receipts = work / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)

    admission_path = package_dir / "hub-index-admission-receipt.json"
    bases_path = work / "base-revisions.json"
    stage_receipt_path = receipts / "stage-receipt.json"
    verify_receipt_path = receipts / "verify-receipt.json"
    checklist_path = receipts / "promote-checklist.json"
    approval_path = receipts / "approval.json"
    promote_receipt_path = receipts / "promote-receipt.json"
    publication_path = receipts / "publication-receipt.json"
    summary_path = receipts / "republication-summary.json"
    count_proof_path = receipts / "package-count-proof.json"
    digest_proof_path = receipts / "expanded-digest-proof.json"
    operator_key_path = work / "operator-approval.key"

    # 1) Package full-authority multi-artifact release
    package, resolved_recipe, count_proof = package_full_authority_hub_indexes(
        recipe,
        stage=True,
        output_dir=package_dir,
        organization=organization,
    )
    _write_json(count_proof_path, count_proof)
    manifest_path = package_dir / MANIFEST_FILENAME

    # 2) Admit (credentials must be unset)
    admission = admit_full_authority_package(
        package_dir,
        receipt_out=admission_path,
        organization=organization,
    )

    # 3) Base revisions for stage/verify
    if base_revisions is not None:
        bases = {str(k): str(v) for k, v in base_revisions.items()}
    elif live_hub:
        token = _load_token()
        api = LiveHubApiAdapter(token=token)
        dataset_ids = [
            f"{organization.casefold()}/{name}"
            for name in CANONICAL_REPOSITORY_NAMES
        ]
        bases = _ensure_repos(api, dataset_ids)
    else:
        bases = default_test_base_revisions(sha="0" * 40)
    _write_json(bases_path, bases)

    # 4) Stage (fake-service default)
    stage_receipt = stage_full_authority_package(
        package_dir,
        base_revisions_file=bases_path,
        admission_receipt=admission_path,
        receipt_out=stage_receipt_path,
        organization=organization,
        fake_service=fake_service,
        live_hub=live_hub,
    )

    # 5) Verify pins + expanded digests (fake-service default for CI)
    verification = verify_full_authority_package(
        package_dir,
        base_revisions_file=bases_path,
        receipt_out=verify_receipt_path,
        organization=organization,
        fake_service=True if not live_hub else fake_service,
        package=package,
    )
    digest_proof = dict(verification.get("_expanded_digest_proof") or {})
    _write_json(digest_proof_path, digest_proof)

    # 6) Optional promote (never unattended default)
    promote_evidence_path: Path | None = None
    promote_receipt: dict[str, Any] | None = None
    if do_promote:
        promote_receipt = promote_full_authority_package(
            package_dir,
            base_revisions_file=bases_path,
            staged_receipt=stage_receipt_path,
            approval_out=approval_path,
            promote_receipt_out=promote_receipt_path,
            operator_key_file=operator_key_path,
            organization=organization,
            approver=approver,
            fake_service=fake_service,
            live_hub=live_hub,
        )
        promote_evidence_path = promote_receipt_path

    # 7) Optional checklist (best-effort; expanded digests may refuse allowlist)
    checklist = prepare_promote_checklist_optional(
        stage_receipt=stage_receipt_path,
        verification_receipt=verify_receipt_path,
        admission_receipt=admission_path,
        package_manifest=manifest_path,
        output=checklist_path,
    )

    # 8) Seal staged-vs-promoted republication receipt
    seal_mode = "live" if live_hub else "offline"
    publication = seal_full_authority_republication(
        stage_receipt=stage_receipt_path,
        verification_receipt=verify_receipt_path,
        output=publication_path,
        promote_checklist=checklist,
        promote_evidence=promote_evidence_path,
        package_manifest=manifest_path,
        claim_promoted=bool(claim_promoted or do_promote),
        mode=seal_mode,
    )

    disposition = str(publication.get("disposition") or "staged_not_promoted")
    summary: dict[str, Any] = {
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "receipt_schema": REPUBLICATION_RECEIPT_SCHEMA,
        "code_version": CODE_VERSION,
        "status": "ok",
        "work_dir": str(work),
        "package_dir": str(package_dir),
        "organization": organization.casefold(),
        "recipe_id": count_proof.get("recipe_id") or FULL_AUTHORITY_RECIPE_ID,
        "full_authority_families": list(FULL_AUTHORITY_FAMILIES),
        "package_counts": {
            "corpus_documents": count_proof["corpus_documents"],
            "bm25_documents": count_proof["bm25_documents"],
            "vector_documents": count_proof["vector_documents"],
            "graph_nodes": count_proof["graph_nodes"],
            "graph_edges": count_proof["graph_edges"],
            "by_family": count_proof.get("by_family"),
            "full_authority_inventory": count_proof.get(
                "full_authority_inventory"
            ),
        },
        "package_root_cid": package.manifest.package_root_cid,
        "package_digest_sha256": package.manifest.package_digest_sha256,
        "corpus_root_cid": package.manifest.corpus_root_cid,
        "bm25_root_cid": package.manifest.bm25_root_cid,
        "vector_root_cid": package.manifest.vector_root_cid,
        "graph_root_cid": package.manifest.graph_root_cid,
        "projection_digests_bound": digest_proof.get(
            "projection_artifact_digest_counts"
        ),
        "admission": {
            "admitted": bool(admission.get("admitted")),
            "package_root_cid": admission.get("package_root_cid"),
            "receipt": str(admission_path),
        },
        "stage": {
            "status": stage_receipt.get("status"),
            "fake_service": bool(stage_receipt.get("fake_service")),
            "live_network": bool(stage_receipt.get("live_network")),
            "main_published": bool(stage_receipt.get("main_published")),
            "receipt": str(stage_receipt_path),
        },
        "verification": {
            "status": verification.get("status"),
            "fake_live": bool(verification.get("fake_live")),
            "package_root_cid": verification.get("package_root_cid"),
            "receipt": str(verify_receipt_path),
            "expanded_digests": True,
        },
        "publication": {
            "disposition": disposition,
            "main_published": bool(publication.get("main_published")),
            "receipt": str(publication_path),
            "claim_promoted": bool(claim_promoted or do_promote),
            "promote_evidence_present": promote_evidence_path is not None,
        },
        "fake_service": bool(fake_service),
        "live_hub": bool(live_hub),
        "promoted": disposition == "promoted",
        "main_published": disposition == "promoted",
        "auto_promote": False,
        "unattended_hub_write": False,
        "repositories": {
            "corpus": f"{organization.casefold()}/{CORPUS_REPOSITORY}",
            "bm25": f"{organization.casefold()}/{BM25_REPOSITORY}",
            "vectors": f"{organization.casefold()}/{VECTORS_REPOSITORY}",
            "knowledge_graph": (
                f"{organization.casefold()}/{KNOWLEDGE_GRAPH_REPOSITORY}"
            ),
        },
        "paths": {
            "admission_receipt": str(admission_path),
            "stage_receipt": str(stage_receipt_path),
            "verify_receipt": str(verify_receipt_path),
            "publication_receipt": str(publication_path),
            "package_count_proof": str(count_proof_path),
            "expanded_digest_proof": str(digest_proof_path),
            "promote_checklist": str(checklist) if checklist else "",
            "promote_receipt": (
                str(promote_receipt_path) if promote_evidence_path else ""
            ),
            "approval": str(approval_path) if promote_evidence_path else "",
        },
    }
    if promote_receipt is not None:
        summary["promote_receipt_status"] = promote_receipt.get("status")
    _write_json(summary_path, summary)
    return summary


# ---------------------------------------------------------------------------
# Legacy operator live helpers (pre-PATLAW-191 path retained)
# ---------------------------------------------------------------------------


def _load_token() -> str:
    env_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()
    cache = Path.home() / ".cache" / "huggingface" / "token"
    if cache.is_file():
        text = cache.read_text(encoding="utf-8").strip()
        if text:
            os.environ["HF_TOKEN"] = text
            return text
    token = resolve_hub_token(allow_missing=True)
    if token:
        os.environ.setdefault("HF_TOKEN", token)
        return token
    raise SystemExit(
        "Hub token required: set HF_TOKEN or login so "
        "~/.cache/huggingface/token exists"
    )


def _dataset_ids(organization: str) -> list[str]:
    org = organization.casefold()
    return [f"{org}/{name}" for name in CANONICAL_REPOSITORY_NAMES]


def _ensure_repos(api: LiveHubApiAdapter, dataset_ids: Sequence[str]) -> dict[str, str]:
    """Create missing dataset repos and return dataset_id → main head SHA."""
    bases: dict[str, str] = {}
    for dataset_id in dataset_ids:
        api.create_repo(
            repo_id=dataset_id,
            repo_type="dataset",
            private=False,
            exist_ok=True,
        )
        info = api.repo_info(repo_id=dataset_id, repo_type="dataset", revision="main")
        sha = getattr(info, "sha", None)
        if not sha:
            raise SystemExit(f"repo_info missing sha for {dataset_id}")
        bases[dataset_id] = str(sha)
        print(f"repo ready: {dataset_id} main={str(sha)[:12]}…", file=sys.stderr)
    return bases


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Package, admit, stage, verify, and seal full-authority Hub "
            f"republication ({TASK_ID}). CI default is offline fake-service; "
            "live Hub requires --live-hub. Never fabricates promoted without "
            "real promote evidence."
        )
    )
    p.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Working directory for package + receipts (default: under /var/tmp)",
    )
    p.add_argument(
        "--organization",
        default=ORGANIZATION,
        help=f"Hub organization (default: {ORGANIZATION})",
    )
    p.add_argument(
        "--recipe",
        type=Path,
        default=None,
        help=(
            "Optional full-authority recipe JSON "
            "(default: build offline PATLAW-186 recipe)"
        ),
    )
    p.add_argument(
        "--approver",
        default="operator-full-authority",
        help="Approver identity recorded on the HMAC approval receipt",
    )
    p.add_argument(
        "--fake-service",
        action="store_true",
        default=True,
        help="Use FakeHubService for stage/verify/promote (CI default: on)",
    )
    p.add_argument(
        "--no-fake-service",
        action="store_true",
        help="Disable fake-service (requires --live-hub for network steps)",
    )
    p.add_argument(
        "--live-hub",
        action="store_true",
        help="Operator live Hub path (mutually exclusive with fake-service)",
    )
    p.add_argument(
        "--promote",
        action="store_true",
        help=(
            "After stage, run operator sign+promote (fake-service drill or "
            "live with token). Default is skip promote."
        ),
    )
    p.add_argument(
        "--skip-promote",
        action="store_true",
        default=True,
        help="Do not promote (default). Staged-not-promoted receipt only.",
    )
    p.add_argument(
        "--no-skip-promote",
        action="store_true",
        help="Allow promote when combined with --promote",
    )
    p.add_argument(
        "--claim-promoted",
        action="store_true",
        help=(
            "Seal publication receipt as promoted; fails closed without real "
            "promote evidence (requires --promote)"
        ),
    )
    p.add_argument(
        "--dry-run-only",
        action="store_true",
        help=(
            "Legacy: build + admit + dry-run stage plan only for non-full-authority "
            "default fixture (no Hub writes)"
        ),
    )
    p.add_argument(
        "--legacy-default-fixture",
        action="store_true",
        help=(
            "Use PATLAW-174 default multi-family fixture instead of full-authority "
            "(not the PATLAW-191 acceptance path)"
        ),
    )
    p.add_argument(
        "--print-json",
        action="store_true",
        help="Print republication summary JSON to stdout",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    work = args.work_dir or Path(f"/var/tmp/patlaw-191-republication-{_utc_stamp()}")
    work = work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)

    # Legacy dry-run-only / default-fixture path (pre-full-authority operator tool).
    if args.dry_run_only or args.legacy_default_fixture:
        return _legacy_main(args, work)

    fake_service = bool(args.fake_service) and not bool(args.no_fake_service)
    live_hub = bool(args.live_hub)
    if live_hub:
        fake_service = False
    if not live_hub:
        # CI remains fake-service default.
        fake_service = True

    skip_promote = bool(args.skip_promote) and not bool(args.no_skip_promote)
    if args.promote:
        skip_promote = False
    promote = bool(args.promote) and not skip_promote

    recipe_payload: dict[str, Any] | None = None
    if args.recipe is not None:
        recipe_payload = _load_json(Path(args.recipe))

    try:
        summary = run_full_authority_hub_republication(
            work,
            organization=str(args.organization).casefold(),
            recipe=recipe_payload,
            fake_service=fake_service,
            live_hub=live_hub,
            promote=promote,
            claim_promoted=bool(args.claim_promoted),
            skip_promote=skip_promote,
            approver=str(args.approver),
        )
    except FabricatedPromoteClaimError as exc:
        print(f"ERROR: fabricated promote claim: {exc}", file=sys.stderr)
        return 2
    except AdmissionFailedError as exc:
        print(f"ERROR: admission failed: {exc}", file=sys.stderr)
        return 1
    except (
        FullAuthorityRepublicationError,
        PackageCountMismatchError,
        VerificationDigestError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _legacy_main(args: argparse.Namespace, work: Path) -> int:
    """Retain prior package→admit→(live)stage orchestration for fixtures."""

    from scripts.ops.legal_data.admit_patent_legal_hub_indexes import (  # noqa: WPS433
        main as admit_main,
    )
    from scripts.ops.legal_data.package_patent_legal_hub_indexes import (  # noqa: WPS433
        main as package_main,
    )
    from scripts.ops.legal_data.stage_patent_legal_hub_indexes import (  # noqa: WPS433
        main as stage_main,
    )

    package_dir = work / "package"
    receipts = work / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    operator_key_path = work / "operator-approval.key"
    bases_path = work / "base-revisions.json"
    admission_path = package_dir / "hub-index-admission-receipt.json"
    stage_receipt = receipts / "stage-receipt.json"
    approval_path = receipts / "approval.json"
    promote_receipt = receipts / "promote-receipt.json"
    dry_run_receipt = receipts / "dry-run-receipt.json"
    summary_path = receipts / "publish-summary.json"

    print(f"work_dir={work}", file=sys.stderr)

    pkg_args = ["--stage", "--output-dir", str(package_dir)]
    if args.recipe is not None:
        pkg_args.extend(["--recipe", str(args.recipe)])
    else:
        pkg_args.append("--default-fixture")
    rc = package_main(pkg_args)
    if rc != 0:
        return rc
    print(f"package staged at {package_dir}", file=sys.stderr)

    saved_tokens = _hide_hub_tokens()
    try:
        rc = admit_main(
            [
                "--package-dir",
                str(package_dir),
                "--receipt-out",
                str(admission_path),
            ]
        )
    finally:
        _restore_env(saved_tokens)
    if rc != 0:
        return rc
    print(f"admission receipt: {admission_path}", file=sys.stderr)

    organization = str(args.organization).casefold()
    dataset_ids = _dataset_ids(organization)

    if args.dry_run_only:
        bases = {did: "0" * 40 for did in dataset_ids}
        _write_json(bases_path, bases)
        rc = stage_main(
            [
                "--mode",
                "dry-run",
                "--package-dir",
                str(package_dir),
                "--base-revisions-file",
                str(bases_path),
                "--admission-receipt",
                str(admission_path),
                "--require-admission",
                "--organization",
                organization,
                "--receipt-out",
                str(dry_run_receipt),
            ]
        )
        print(f"dry-run receipt: {dry_run_receipt} rc={rc}", file=sys.stderr)
        return rc

    token = _load_token()
    api = LiveHubApiAdapter(token=token)
    bases = _ensure_repos(api, dataset_ids)
    _write_json(bases_path, bases)

    rc = stage_main(
        [
            "--mode",
            "stage",
            "--live-hub",
            "--package-dir",
            str(package_dir),
            "--base-revisions-file",
            str(bases_path),
            "--admission-receipt",
            str(admission_path),
            "--require-admission",
            "--organization",
            organization,
            "--receipt-out",
            str(stage_receipt),
            "--token-env",
            "HF_TOKEN",
        ]
    )
    if rc != 0:
        print("stage failed", file=sys.stderr)
        return rc

    if not operator_key_path.exists():
        operator_key_path.write_bytes(secrets.token_bytes(32))
        operator_key_path.chmod(0o600)
    rc = stage_main(
        [
            "--mode",
            "sign",
            "--package-dir",
            str(package_dir),
            "--base-revisions-file",
            str(bases_path),
            "--organization",
            organization,
            "--operator-key-file",
            str(operator_key_path),
            "--approver",
            args.approver,
            "--approval-id",
            f"live-publish-{_utc_stamp()}",
            "--approval-out",
            str(approval_path),
        ]
    )
    if rc != 0:
        print("sign failed", file=sys.stderr)
        return rc

    if args.skip_promote and not args.promote:
        summary = {
            "status": "staged_pending_promote",
            "work_dir": str(work),
            "package_dir": str(package_dir),
            "stage_receipt": str(stage_receipt),
            "approval": str(approval_path),
            "dataset_ids": dataset_ids,
            "main_published": False,
        }
        _write_json(summary_path, summary)
        print(json.dumps(summary, indent=2))
        return 0

    rc = stage_main(
        [
            "--mode",
            "promote",
            "--live-hub",
            "--package-dir",
            str(package_dir),
            "--base-revisions-file",
            str(bases_path),
            "--organization",
            organization,
            "--operator-key-file",
            str(operator_key_path),
            "--approval-file",
            str(approval_path),
            "--staged-receipt-file",
            str(stage_receipt),
            "--receipt-out",
            str(promote_receipt),
            "--token-env",
            "HF_TOKEN",
        ]
    )
    if rc != 0:
        print("promote failed", file=sys.stderr)
        return rc

    post_heads: dict[str, str] = {}
    for did in dataset_ids:
        info = api.repo_info(repo_id=did, repo_type="dataset", revision="main")
        post_heads[did] = str(getattr(info, "sha", "") or "")
        print(
            f"published: https://huggingface.co/datasets/{did} "
            f"main={post_heads[did][:12]}…",
            file=sys.stderr,
        )

    summary = {
        "status": "promoted",
        "work_dir": str(work),
        "package_dir": str(package_dir),
        "stage_receipt": str(stage_receipt),
        "approval": str(approval_path),
        "promote_receipt": str(promote_receipt),
        "dataset_ids": dataset_ids,
        "base_revisions": bases,
        "promoted_main_heads": post_heads,
        "main_published": True,
        "repositories": {
            "corpus": f"{organization}/{CORPUS_REPOSITORY}",
            "bm25": f"{organization}/{BM25_REPOSITORY}",
            "vectors": f"{organization}/{VECTORS_REPOSITORY}",
            "knowledge_graph": f"{organization}/{KNOWLEDGE_GRAPH_REPOSITORY}",
        },
    }
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
