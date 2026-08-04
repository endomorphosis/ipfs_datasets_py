"""Release tests: full-authority Hub republication (PATLAW-191).

Acceptance:

* Package counts reflect the full-authority corpus
* Admission passes DLP / rights / Viewer gates
* Verification binds expanded artifact digests for every projection
* Receipt cannot claim promoted without real promote evidence
* CI remains fake-service default (no live Hub, no unattended main promote)

Validation:

    python -m pytest tests/release/test_full_authority_hub_republication.py -q
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    CANONICAL_REPOSITORY_NAMES,
    ORGANIZATION,
)
from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (
    reject_credentials_in_payload,
)
from ipfs_datasets_py.processors.domains.patent.hub_index_package import (
    INDEX_FAMILIES,
    MANIFEST_FILENAME,
    load_package_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_SCRIPT = (
    REPO_ROOT / "scripts/ops/legal_data/publish_patent_legal_hub_indexes_live.py"
)
DOCS_PATH = (
    REPO_ROOT / "docs/operations/PATENT_LEGAL_FULL_AUTHORITY_CORPUS.md"
)
MATERIALIZE_SCRIPT = (
    REPO_ROOT / "scripts/ops/legal_data/materialize_public_legal_corpus.py"
)
BM25_SCRIPT = (
    REPO_ROOT / "scripts/ops/legal_data/build_public_legal_bm25_index.py"
)
VECTOR_SCRIPT = (
    REPO_ROOT / "scripts/ops/legal_data/build_public_legal_vector_index.py"
)
GRAPH_SCRIPT = (
    REPO_ROOT / "scripts/ops/legal_data/build_public_legal_knowledge_graph.py"
)
SEAL_SCRIPT = (
    REPO_ROOT
    / "scripts/ops/legal_data/seal_patent_legal_hub_index_publication_receipt.py"
)


def _load_module(path: Path, module_name: str):
    assert path.is_file(), f"missing script at {path}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pub_mod():
    return _load_module(
        PUBLISH_SCRIPT, "publish_patent_legal_hub_indexes_live_patlaw191"
    )


@pytest.fixture(scope="module")
def full_recipe(pub_mod):
    return pub_mod.load_full_authority_recipe(assert_complete=True)


@pytest.fixture(scope="module")
def baseline_package(tmp_path_factory: pytest.TempPathFactory, pub_mod, full_recipe):
    """Module-scoped full-authority package (expensive offline build once)."""
    root = tmp_path_factory.mktemp("fa-hub-package")
    package, recipe, count_proof = pub_mod.package_full_authority_hub_indexes(
        full_recipe,
        stage=True,
        output_dir=root,
    )
    return {
        "package_dir": root,
        "package": package,
        "recipe": recipe,
        "count_proof": count_proof,
    }


@pytest.fixture(scope="module")
def republication(
    tmp_path_factory: pytest.TempPathFactory, pub_mod, full_recipe
):
    """Module-scoped CI fake-service republication (package→admit→stage→verify→seal)."""
    work = tmp_path_factory.mktemp("fa-hub-republication")
    summary = pub_mod.run_full_authority_hub_republication(
        work,
        recipe=full_recipe,
        fake_service=True,
        live_hub=False,
        promote=False,
        claim_promoted=False,
        skip_promote=True,
    )
    return {"work": work, "summary": summary}


def _json_blob(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _assert_no_credentials(payload: object) -> None:
    reject_credentials_in_payload(payload, label="patlaw191_receipt")
    text = _json_blob(payload)
    lowered = text.casefold()
    assert "bearer " not in lowered
    assert "password=" not in lowered
    assert "fake-operator-token" not in text
    assert not re.search(r"(?<![a-z0-9_-])hf_[A-Za-z0-9]{12,}", text)


# ---------------------------------------------------------------------------
# Declared outputs / pins
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert PUBLISH_SCRIPT.is_file()
    assert DOCS_PATH.is_file()
    assert Path(__file__).is_file()
    assert MATERIALIZE_SCRIPT.is_file()
    assert BM25_SCRIPT.is_file()
    assert VECTOR_SCRIPT.is_file()
    assert GRAPH_SCRIPT.is_file()
    assert SEAL_SCRIPT.is_file()


def test_module_identity_pins(pub_mod) -> None:
    assert pub_mod.TASK_ID == "PATLAW-191"
    assert pub_mod.GOAL_ID == "PATLAW-G218"
    assert pub_mod.FULL_AUTHORITY_RECIPE_ID == (
        "patlaw-full-authority-public-legal-corpus"
    )
    assert tuple(pub_mod.FULL_AUTHORITY_FAMILIES) == ("cfr", "mpep", "guidance")
    assert tuple(pub_mod.PROJECTION_FAMILIES) == (
        "corpus",
        "bm25",
        "vectors",
        "knowledge_graph",
    )
    assert set(INDEX_FAMILIES) == {"bm25", "vectors", "knowledge_graph"}


def test_docs_cover_full_authority_republication() -> None:
    text = DOCS_PATH.read_text(encoding="utf-8")
    assert "PATLAW-191" in text
    assert "full-authority" in text.casefold() or "Full-authority" in text
    assert "fake-service" in text or "fake_service" in text
    assert "promoted" in text.casefold()
    assert "publish_patent_legal_hub_indexes_live.py" in text
    assert "test_full_authority_hub_republication.py" in text


# ---------------------------------------------------------------------------
# Package counts reflect full-authority corpus
# ---------------------------------------------------------------------------


def test_package_counts_reflect_full_authority_corpus(
    baseline_package, full_recipe
) -> None:
    package = baseline_package["package"]
    proof = baseline_package["count_proof"]
    recipe_docs = int(full_recipe["counts"]["documents"])
    by_family = dict(full_recipe["counts"]["by_family"])

    assert proof["ok"] is True
    assert package.manifest.counts.corpus_documents == recipe_docs
    assert package.manifest.counts.bm25_documents == recipe_docs
    assert package.manifest.counts.vector_documents == recipe_docs
    assert proof["corpus_documents"] == recipe_docs
    assert proof["bm25_documents"] == recipe_docs
    assert proof["vector_documents"] == recipe_docs
    assert proof["full_authority_complete"] is True
    assert full_recipe["full_authority"]["complete"] is True

    for family in ("cfr", "mpep", "guidance"):
        assert int(by_family.get(family) or 0) >= 1
        assert int(proof["by_family"].get(family) or 0) >= 1

    fa_inv = full_recipe["counts"]["full_authority"]
    assert int(fa_inv.get("cfr_inventory_total") or 0) >= 1
    assert int(fa_inv.get("mpep_section_level") or 0) >= 1
    assert int(fa_inv.get("guidance_pdfs") or 0) >= 1
    assert package.manifest.package_root_cid
    assert package.manifest.corpus_root_cid
    assert package.manifest.bm25_root_cid
    assert package.manifest.vector_root_cid
    assert package.manifest.graph_root_cid


def test_assert_package_counts_helper_rejects_mismatch(
    pub_mod, baseline_package, full_recipe
) -> None:
    package = baseline_package["package"]
    bad_recipe = json.loads(json.dumps(full_recipe))
    bad_recipe["counts"]["documents"] = int(full_recipe["counts"]["documents"]) + 99
    with pytest.raises(pub_mod.PackageCountMismatchError):
        pub_mod.assert_package_counts_reflect_full_authority(package, bad_recipe)


def test_package_manifest_on_disk(baseline_package) -> None:
    package_dir: Path = baseline_package["package_dir"]
    manifest_path = package_dir / MANIFEST_FILENAME
    assert manifest_path.is_file()
    loaded = load_package_manifest(manifest_path)
    assert loaded.counts.corpus_documents == (
        baseline_package["package"].manifest.counts.corpus_documents
    )
    assert set(loaded.index_families_present) == set(INDEX_FAMILIES)


# ---------------------------------------------------------------------------
# Admission passes
# ---------------------------------------------------------------------------


def test_admission_passes(republication, pub_mod) -> None:
    summary = republication["summary"]
    work: Path = republication["work"]
    admission_path = Path(summary["paths"]["admission_receipt"])
    assert admission_path.is_file()
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    assert admission["admitted"] is True
    assert summary["admission"]["admitted"] is True
    assert admission.get("package_root_cid") == summary["package_root_cid"]
    _assert_no_credentials(admission)

    # Direct helper also admits the staged package directory.
    package_dir = Path(summary["package_dir"])
    out = work / "receipts" / "admission-retry.json"
    again = pub_mod.admit_full_authority_package(
        package_dir, receipt_out=out, organization=ORGANIZATION
    )
    assert again["admitted"] is True


# ---------------------------------------------------------------------------
# Verification binds expanded digests
# ---------------------------------------------------------------------------


def test_verification_binds_expanded_digests(republication, pub_mod) -> None:
    summary = republication["summary"]
    verify_path = Path(summary["paths"]["verify_receipt"])
    assert verify_path.is_file()
    verification = json.loads(verify_path.read_text(encoding="utf-8"))

    assert verification.get("package_root_cid") == summary["package_root_cid"]
    projection_digests = verification.get("projection_digests") or {}
    for family in pub_mod.PROJECTION_FAMILIES:
        assert family in projection_digests
        family_map = projection_digests[family]
        assert isinstance(family_map, dict)
        assert len(family_map) >= 1
        for rel_path, digest in family_map.items():
            assert rel_path
            assert re.fullmatch(r"[0-9a-f]{64}", str(digest).casefold())

    # Expanded: multi-artifact inventories, not a single opaque hash per family.
    multi = sum(1 for m in projection_digests.values() if len(m) > 1)
    assert multi >= 1

    proof = pub_mod.assert_verification_binds_expanded_digests(verification)
    assert proof["ok"] is True
    assert proof["expanded"] is True
    assert summary["verification"]["expanded_digests"] is True
    assert summary["projection_digests_bound"]
    for family in pub_mod.PROJECTION_FAMILIES:
        assert int(summary["projection_digests_bound"][family]) >= 1

    _assert_no_credentials(verification)


def test_verification_digest_helper_rejects_missing_family(
    pub_mod, republication
) -> None:
    verify_path = Path(republication["summary"]["paths"]["verify_receipt"])
    verification = json.loads(verify_path.read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(verification))
    del bad["projection_digests"]["bm25"]
    with pytest.raises(pub_mod.VerificationDigestError, match="bm25"):
        pub_mod.assert_verification_binds_expanded_digests(bad)


# ---------------------------------------------------------------------------
# Receipt cannot claim promoted without real promote evidence
# ---------------------------------------------------------------------------


def test_staged_receipt_is_not_promoted(republication) -> None:
    summary = republication["summary"]
    pub_path = Path(summary["paths"]["publication_receipt"])
    assert pub_path.is_file()
    publication = json.loads(pub_path.read_text(encoding="utf-8"))

    assert publication["disposition"] == "staged_not_promoted"
    assert publication.get("main_published") is False
    assert summary["publication"]["disposition"] == "staged_not_promoted"
    assert summary["promoted"] is False
    assert summary["main_published"] is False
    assert summary["auto_promote"] is False
    assert summary["publication"]["promote_evidence_present"] is False
    _assert_no_credentials(publication)
    _assert_no_credentials(summary)


def test_claim_promoted_without_evidence_fails_closed(
    pub_mod, republication
) -> None:
    work: Path = republication["work"]
    summary = republication["summary"]
    stage_path = Path(summary["paths"]["stage_receipt"])
    verify_path = Path(summary["paths"]["verify_receipt"])
    out = work / "receipts" / "fabricated-promote.json"

    with pytest.raises(pub_mod.FabricatedPromoteClaimError):
        pub_mod.seal_full_authority_republication(
            stage_receipt=stage_path,
            verification_receipt=verify_path,
            output=out,
            promote_evidence=None,
            claim_promoted=True,
            mode="offline",
        )
    assert not out.exists()


def test_orchestrator_claim_promoted_without_promote_fails(
    pub_mod, full_recipe, tmp_path: Path
) -> None:
    with pytest.raises(pub_mod.FabricatedPromoteClaimError):
        pub_mod.run_full_authority_hub_republication(
            tmp_path / "bad-claim",
            recipe=full_recipe,
            fake_service=True,
            promote=False,
            claim_promoted=True,
            skip_promote=True,
        )


def test_promoted_with_real_fake_service_evidence(
    pub_mod, full_recipe, tmp_path_factory: pytest.TempPathFactory
) -> None:
    work = tmp_path_factory.mktemp("fa-hub-promote-drill")
    summary = pub_mod.run_full_authority_hub_republication(
        work,
        recipe=full_recipe,
        fake_service=True,
        live_hub=False,
        promote=True,
        claim_promoted=True,
        skip_promote=False,
    )
    assert summary["promoted"] is True
    assert summary["main_published"] is True
    assert summary["fake_service"] is True
    assert summary["publication"]["disposition"] == "promoted"
    assert summary["publication"]["promote_evidence_present"] is True
    promote_path = Path(summary["paths"]["promote_receipt"])
    assert promote_path.is_file()
    promote = json.loads(promote_path.read_text(encoding="utf-8"))
    assert promote.get("status") in {"promoted", "ok"} or promote.get(
        "main_published"
    )
    assert bool(promote.get("fake_service", True)) is True
    _assert_no_credentials(summary)


# ---------------------------------------------------------------------------
# CI remains fake-service default
# ---------------------------------------------------------------------------


def test_ci_default_is_fake_service(republication, pub_mod) -> None:
    summary = republication["summary"]
    assert summary["fake_service"] is True
    assert summary["live_hub"] is False
    assert summary["stage"]["fake_service"] is True
    assert summary["stage"]["live_network"] is False
    assert summary["stage"]["main_published"] is False
    assert summary["auto_promote"] is False
    assert summary["unattended_hub_write"] is False

    stage_path = Path(summary["paths"]["stage_receipt"])
    stage = json.loads(stage_path.read_text(encoding="utf-8"))
    assert stage.get("fake_service") is True
    assert stage.get("live_network") is False
    assert stage.get("main_published") is False
    assert stage.get("tokens_used") in (False, None, 0)

    # Default CLI flags: fake-service on, skip-promote on.
    parser = pub_mod._parser()
    ns = parser.parse_args([])
    assert ns.fake_service is True
    assert ns.live_hub is False
    assert ns.skip_promote is True
    assert ns.promote is False


def test_fake_service_and_live_hub_exclusive(pub_mod, full_recipe, tmp_path: Path) -> None:
    with pytest.raises(pub_mod.FullAuthorityRepublicationError):
        pub_mod.run_full_authority_hub_republication(
            tmp_path / "exclusive",
            recipe=full_recipe,
            fake_service=True,
            live_hub=True,
        )


def test_stage_and_verify_helpers_default_fake_service(
    pub_mod, republication, tmp_path: Path
) -> None:
    """Re-stage / re-verify the packaged tree with explicit fake-service."""
    summary = republication["summary"]
    package_dir = Path(summary["package_dir"])
    work = Path(summary["work_dir"]) if "work_dir" in summary else republication["work"]
    bases = work / "base-revisions.json"
    assert bases.is_file()
    admission = Path(summary["paths"]["admission_receipt"])

    stage_out = tmp_path / "stage-again.json"
    stage = pub_mod.stage_full_authority_package(
        package_dir,
        base_revisions_file=bases,
        admission_receipt=admission,
        receipt_out=stage_out,
        fake_service=True,
        live_hub=False,
    )
    assert stage.get("fake_service") is True

    verify_out = tmp_path / "verify-again.json"
    verification = pub_mod.verify_full_authority_package(
        package_dir,
        base_revisions_file=bases,
        receipt_out=verify_out,
        fake_service=True,
        verified_cache_root=tmp_path / "verified-cache-again",
    )
    assert verification.get("fake_live") is True or verification.get(
        "status"
    ) in {"fake_live_complete", "ok", "verified"}
    pub_mod.assert_verification_binds_expanded_digests(verification)


# ---------------------------------------------------------------------------
# End-to-end summary integrity
# ---------------------------------------------------------------------------


def test_republication_summary_binds_repositories_and_counts(
    republication, full_recipe
) -> None:
    summary = republication["summary"]
    assert summary["task_id"] == "PATLAW-191"
    assert summary["goal_id"] == "PATLAW-G218"
    assert summary["status"] == "ok"
    assert summary["organization"] == ORGANIZATION
    assert summary["package_counts"]["corpus_documents"] == (
        full_recipe["counts"]["documents"]
    )
    repos = summary["repositories"]
    for name in CANONICAL_REPOSITORY_NAMES:
        assert any(name in value for value in repos.values())
    assert set(summary["full_authority_families"]) == {
        "cfr",
        "mpep",
        "guidance",
    }

    summary_path = (
        Path(summary["package_dir"]).parent
        / "receipts"
        / "republication-summary.json"
    )
    assert summary_path.is_file()
    on_disk = json.loads(summary_path.read_text(encoding="utf-8"))
    assert on_disk["package_root_cid"] == summary["package_root_cid"]
    _assert_no_credentials(on_disk)


def test_cli_main_fake_service_path(
    pub_mod, full_recipe, tmp_path_factory: pytest.TempPathFactory
) -> None:
    work = tmp_path_factory.mktemp("fa-hub-cli")
    recipe_path = work / "recipe.json"
    recipe_path.write_text(
        json.dumps(full_recipe, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rc = pub_mod.main(
        [
            "--work-dir",
            str(work / "run"),
            "--recipe",
            str(recipe_path),
            "--fake-service",
            "--skip-promote",
            "--print-json",
        ]
    )
    assert rc == 0
    summary_path = work / "run" / "receipts" / "republication-summary.json"
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["fake_service"] is True
    assert summary["promoted"] is False
    assert summary["package_counts"]["corpus_documents"] == (
        full_recipe["counts"]["documents"]
    )
