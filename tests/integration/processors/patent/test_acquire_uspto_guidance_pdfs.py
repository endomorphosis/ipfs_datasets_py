"""Integration tests: USPTO guidance PDF acquisition (PATLAW-185).

Acceptance:

* Inventory PDFs download (or offline-materialize) and hash-verify
* Text extraction is stable for identical PDF bytes
* Non-public or failed-auth packages fail closed
* Offline catalog is sufficient for CI (no network / no Hub)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.uspto_guidance_pdf_contracts import (
    AUTHORITY_TIER_GUIDANCE,
    MANIFEST_FILENAME,
    REQUIRED_DOCUMENT_IDS,
    REQUIRED_GUIDANCE_DOCUMENTS,
    SCHEMA_VERSION,
    InventoryEntryStatus,
    PrivateOrNonPublicError,
    UnpinnedLatestSelectionError,
    content_sha256,
    deterministic_text_digest,
    validate_extraction_determinism,
    validate_manifest_dict,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "acquire_uspto_guidance_pdfs.py"
)


def _load_acquire_module():
    assert _SCRIPT_PATH.is_file(), f"missing acquisition CLI at {_SCRIPT_PATH}"
    module_name = "acquire_uspto_guidance_pdfs_patlaw185"
    spec = importlib.util.spec_from_file_location(module_name, _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def acquire_mod():
    return _load_acquire_module()


@pytest.fixture(scope="module")
def acquisition(acquire_mod):
    return acquire_mod.acquire_uspto_guidance_pdfs(
        stage=False,
        mode="acquire",
    )


# ---------------------------------------------------------------------------
# Pins / module surface
# ---------------------------------------------------------------------------


def test_acquire_module_pins(acquire_mod) -> None:
    assert acquire_mod.ACQUIRE_TASK_ID == "PATLAW-185"
    assert acquire_mod.ACQUIRE_GOAL_ID == "PATLAW-G217"
    assert acquire_mod.ACQUIRE_SCHEMA_VERSION.startswith(
        "patent.uspto_guidance_pdfs.acquisition"
    )
    assert acquire_mod.RECEIPT_FILENAME.endswith(".json")
    assert acquire_mod.PDFS_DIRNAME == "pdfs"
    assert acquire_mod.TEXTS_DIRNAME == "texts"


def test_required_catalog_is_nonempty() -> None:
    assert len(REQUIRED_GUIDANCE_DOCUMENTS) >= 5
    assert "sme-2019-peg" in REQUIRED_DOCUMENT_IDS
    assert "sme-2024-ai-examples" in REQUIRED_DOCUMENT_IDS


# ---------------------------------------------------------------------------
# Inventory + hash verification
# ---------------------------------------------------------------------------


def test_inventory_covers_required_catalog_and_hash_verifies(acquisition) -> None:
    manifest = acquisition.manifest
    assert manifest.schema_version == SCHEMA_VERSION
    assert manifest.authority_tier == AUTHORITY_TIER_GUIDANCE
    assert manifest.is_binding is False
    assert manifest.partition == "public"
    assert "latest" not in manifest.edition_pin.document_id.lower()
    assert "latest" not in manifest.edition_pin.version.lower()

    assert len(manifest.inventory) >= len(REQUIRED_GUIDANCE_DOCUMENTS)
    present_ids = {
        e.document_id
        for e in manifest.inventory
        if e.status is InventoryEntryStatus.PRESENT
    }
    assert REQUIRED_DOCUMENT_IDS.issubset(present_ids)

    # Every present PDF binds URI, sha256, publication/cutoff, rights, pages.
    for entry in manifest.inventory:
        if entry.status is not InventoryEntryStatus.PRESENT:
            continue
        assert entry.uri.startswith("https://")
        assert len(entry.sha256) == 64
        assert entry.publication_date is not None
        assert entry.cutoff is not None
        assert entry.rights_review.reviewed_for_release
        assert entry.page_count >= 1
        assert entry.is_binding is False
        assert entry.authority_tier == "guidance"
        assert entry.classification in {"public_official", "public_user"}

        key = f"{entry.document_id}-v{entry.version}"
        assert key in acquisition.pdf_bytes
        actual = content_sha256(acquisition.pdf_bytes[key])
        assert actual == entry.sha256
        assert acquisition.pdf_bytes[key].startswith(b"%PDF")
        assert entry.metadata.get("hash_verified") is True

    assert acquisition.receipt["hash_verified"] == len(
        [e for e in manifest.inventory if e.status is InventoryEntryStatus.PRESENT]
    )
    assert acquisition.receipt["hash_verified_ok"] is True


def test_package_digest_and_cid_bind_acquisition(acquisition) -> None:
    assert acquisition.package_digest_sha256
    assert len(acquisition.package_digest_sha256) == 64
    assert acquisition.package_root_cid.startswith("b")
    assert len(acquisition.package_root_cid) >= 20
    assert (
        acquisition.manifest.package_digest_sha256
        == acquisition.package_digest_sha256
    )
    assert acquisition.manifest.package_root_cid == acquisition.package_root_cid
    assert acquisition.manifest.inventory_digest_sha256
    assert len(acquisition.manifest.inventory_digest_sha256) == 64


def test_receipt_binds_digests_and_rejects_hub_upload(acquisition) -> None:
    receipt = dict(acquisition.receipt)
    assert receipt["task_id"] == "PATLAW-185"
    assert receipt["goal_id"] == "PATLAW-G217"
    assert receipt["package_digest_sha256"] == acquisition.package_digest_sha256
    assert receipt["package_root_cid"] == acquisition.package_root_cid
    assert receipt["hub_upload"] is False
    assert receipt["non_public_rejected"] is True
    assert receipt["failed_auth_rejected"] is True
    assert receipt["extraction_deterministic"] is True
    assert receipt["source_kind"] == "uspto-guidance-offline-catalog"
    assert receipt["authority_tier"] == "guidance"
    assert receipt["is_binding"] is False
    assert receipt["documents_present"] >= len(REQUIRED_GUIDANCE_DOCUMENTS)
    assert receipt["with_extraction"] >= len(REQUIRED_GUIDANCE_DOCUMENTS)
    assert receipt["hash_verified"] >= 1


def test_superseded_editions_are_retained(acquisition) -> None:
    # Both 2019 PEG and 2024 AI examples remain in inventory (evidence).
    ids = {e.document_id for e in acquisition.manifest.inventory}
    assert "sme-2019-peg" in ids
    assert "sme-2019-peg-october-update" in ids
    assert "sme-2024-ai-examples" in ids
    assert acquisition.manifest.supersessions
    assert acquisition.manifest.counts.supersession_edges >= 1


# ---------------------------------------------------------------------------
# Deterministic text extraction
# ---------------------------------------------------------------------------


def test_text_extraction_present_and_stable_for_identical_bytes(
    acquire_mod, acquisition
) -> None:
    extractor = acquire_mod.PdfTextExtractor()
    assert acquisition.manifest.counts.with_extraction == len(
        [
            e
            for e in acquisition.manifest.inventory
            if e.status is InventoryEntryStatus.PRESENT and e.extraction is not None
        ]
    )

    for entry in acquisition.manifest.inventory:
        if entry.status is not InventoryEntryStatus.PRESENT:
            continue
        assert entry.extraction is not None
        assert len(entry.extraction.text_sha256) == 64
        assert entry.extraction.page_count == entry.page_count
        assert entry.extraction.method == acquire_mod.DEFAULT_EXTRACTION_METHOD

        key = f"{entry.document_id}-v{entry.version}"
        pdf = acquisition.pdf_bytes[key]
        # Two independent extraction passes yield one digest.
        dig = extractor.assert_deterministic(pdf)
        assert dig == entry.extraction.text_sha256

        text = acquisition.extracted_texts[key]
        assert text.strip()
        assert deterministic_text_digest(text) == entry.extraction.text_sha256

        # Contract helper agrees.
        text_a, _ = extractor.extract_raw(pdf)
        text_b, _ = extractor.extract_raw(pdf)
        assert (
            validate_extraction_determinism(
                pdf_bytes=pdf, text_a=text_a, text_b=text_b
            )
            == dig
        )


def test_identical_pdf_bytes_always_same_sha256(acquire_mod) -> None:
    spec = REQUIRED_GUIDANCE_DOCUMENTS[0]
    a = acquire_mod.synthesize_pdf_for_spec(spec)
    b = acquire_mod.synthesize_pdf_for_spec(spec)
    assert a == b
    assert content_sha256(a) == content_sha256(b)
    assert a.startswith(b"%PDF")


def test_hash_mismatch_fails_closed(acquire_mod) -> None:
    pdf = acquire_mod.synthesize_pdf_for_spec(REQUIRED_GUIDANCE_DOCUMENTS[0])
    wrong = "0" * 64
    with pytest.raises(acquire_mod.HashVerificationError):
        acquire_mod.verify_pdf_sha256(pdf, expected_sha256=wrong, label="test")


# ---------------------------------------------------------------------------
# Non-public / failed-auth fail-closed
# ---------------------------------------------------------------------------


def test_non_public_flag_is_rejected(acquire_mod) -> None:
    with pytest.raises(acquire_mod.NonPublicPackageError):
        acquire_mod.acquire_uspto_guidance_pdfs(non_public=True)


def test_failed_auth_flag_is_rejected(acquire_mod) -> None:
    with pytest.raises(acquire_mod.AuthFailedError):
        acquire_mod.acquire_uspto_guidance_pdfs(failed_auth=True)


def test_assert_public_package_rejects_private_classification(acquire_mod) -> None:
    with pytest.raises(acquire_mod.NonPublicPackageError):
        acquire_mod.assert_public_package(
            classification="private_confidential",
            label="test",
        )
    with pytest.raises(acquire_mod.NonPublicPackageError):
        acquire_mod.assert_public_package(
            {"partition": "private", "classification": "public_official"},
            label="test",
        )
    with pytest.raises(acquire_mod.NonPublicPackageError):
        acquire_mod.assert_public_package(
            {"private": True},
            label="test",
        )


def test_assert_public_package_rejects_failed_auth(acquire_mod) -> None:
    with pytest.raises(acquire_mod.AuthFailedError):
        acquire_mod.assert_public_package(
            {"auth_required": True, "auth_ok": False},
            label="test",
        )
    with pytest.raises(acquire_mod.AuthFailedError):
        acquire_mod.assert_public_package(
            auth_required=True,
            auth_ok=False,
            label="test",
        )


def test_package_recipe_non_public_fails_closed(
    acquire_mod, tmp_path: Path
) -> None:
    recipe = {
        "classification": "private_internal",
        "partition": "private",
        "auth_required": False,
        "documents": [
            {
                "document_id": "sme-2019-peg",
                "version": "2019-01-07",
            }
        ],
    }
    path = tmp_path / "private_package.json"
    path.write_text(json.dumps(recipe), encoding="utf-8")
    with pytest.raises(
        (acquire_mod.NonPublicPackageError, PrivateOrNonPublicError)
    ):
        acquire_mod.acquire_uspto_guidance_pdfs(fixture_path=path)


def test_package_recipe_failed_auth_fails_closed(
    acquire_mod, tmp_path: Path
) -> None:
    recipe = {
        "classification": "public_official",
        "partition": "public",
        "auth_required": True,
        "auth_ok": False,
        "documents": [
            {
                "document_id": "sme-2019-peg",
                "version": "2019-01-07",
            }
        ],
    }
    path = tmp_path / "auth_fail_package.json"
    path.write_text(json.dumps(recipe), encoding="utf-8")
    with pytest.raises(acquire_mod.AuthFailedError):
        acquire_mod.acquire_uspto_guidance_pdfs(fixture_path=path)


def test_cli_reject_non_public_exits_nonzero(acquire_mod) -> None:
    code = acquire_mod.main(["--reject-non-public"])
    assert code == 2


def test_cli_reject_failed_auth_exits_nonzero(acquire_mod) -> None:
    code = acquire_mod.main(["--reject-failed-auth"])
    assert code == 2


# ---------------------------------------------------------------------------
# Identity pins / live fail-closed
# ---------------------------------------------------------------------------


def test_unpinned_latest_cutoff_is_rejected(acquire_mod) -> None:
    with pytest.raises((UnpinnedLatestSelectionError, Exception)):
        acquire_mod.acquire_uspto_guidance_pdfs(cutoff="latest")


def test_live_mode_fails_closed(acquire_mod) -> None:
    with pytest.raises(acquire_mod.LiveAcquisitionUnavailableError):
        acquire_mod.acquire_uspto_guidance_pdfs(live=True)


def test_cli_live_exits_nonzero(acquire_mod) -> None:
    code = acquire_mod.main(["--default-catalog", "--live"])
    assert code == 2


# ---------------------------------------------------------------------------
# Staging + CLI
# ---------------------------------------------------------------------------


def test_stage_writes_manifest_receipt_pdfs_and_texts(
    acquire_mod, tmp_path: Path
) -> None:
    out = tmp_path / "uspto-guidance-pdfs"
    result = acquire_mod.acquire_uspto_guidance_pdfs(
        output_dir=out,
        stage=True,
    )
    assert result.output_dir == out
    manifest_path = out / MANIFEST_FILENAME
    receipt_path = out / acquire_mod.RECEIPT_FILENAME
    meta_path = out / acquire_mod.PACKAGE_META_FILENAME
    pdfs_dir = out / acquire_mod.PDFS_DIRNAME
    texts_dir = out / acquire_mod.TEXTS_DIRNAME

    assert manifest_path.is_file()
    assert receipt_path.is_file()
    assert meta_path.is_file()
    assert pdfs_dir.is_dir()
    assert texts_dir.is_dir()

    staged = json.loads(manifest_path.read_text(encoding="utf-8"))
    validated = validate_manifest_dict(staged)
    assert validated.package_digest_sha256 == result.package_digest_sha256
    assert validated.package_root_cid == result.package_root_cid

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["task_id"] == "PATLAW-185"
    assert receipt["package_digest_sha256"] == result.package_digest_sha256
    assert receipt["hub_upload"] is False

    pdf_files = sorted(pdfs_dir.glob("*.pdf"))
    text_files = sorted(texts_dir.glob("*.txt"))
    assert len(pdf_files) == len(result.pdf_bytes)
    assert len(text_files) == len(result.extracted_texts)
    assert len(pdf_files) >= len(REQUIRED_GUIDANCE_DOCUMENTS)

    for path in pdf_files:
        data = path.read_bytes()
        assert data.startswith(b"%PDF")
        # Hash-verify staged PDF against inventory.
        digest = content_sha256(data)
        matching = [
            e
            for e in validated.inventory
            if e.sha256 == digest and e.status is InventoryEntryStatus.PRESENT
        ]
        assert matching, f"staged PDF {path.name} sha256 not in inventory"

    for path in text_files:
        assert path.read_text(encoding="utf-8").strip()


def test_cli_default_catalog_dry_run(acquire_mod) -> None:
    code = acquire_mod.main(
        ["--default-catalog", "--no-print-summary"]
    )
    assert code == 0


def test_cli_default_catalog_stage_and_validate(
    acquire_mod, tmp_path: Path, capsys
) -> None:
    out = tmp_path / "staged"
    code = acquire_mod.main(
        [
            "--default-catalog",
            "--stage",
            "--output-dir",
            str(out),
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "package_digest_sha256" in captured.out
    assert "package_root_cid" in captured.out
    assert "hash_verified" in captured.out
    assert "non_public_rejected" in captured.out
    assert "hub_upload" in captured.out

    code = acquire_mod.main(
        ["--validate-manifest", str(out / MANIFEST_FILENAME)]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "manifest_ok: true" in captured.out


def test_acquire_from_public_package_recipe(
    acquire_mod, tmp_path: Path
) -> None:
    # Build expected digests from synthesis so hash-verify is meaningful.
    specs = list(REQUIRED_GUIDANCE_DOCUMENTS)[:2]
    documents = []
    for spec in specs:
        pdf = acquire_mod.synthesize_pdf_for_spec(spec)
        documents.append(
            {
                "document_id": spec.document_id,
                "version": spec.version,
                "title": spec.title,
                "topic": spec.topic,
                "publication_date": spec.publication_date,
                "cutoff": spec.cutoff,
                "uri": spec.uri,
                "page_count": spec.page_count,
                "expected_sha256": content_sha256(pdf),
            }
        )
    recipe = {
        "classification": "public_official",
        "partition": "public",
        "auth_required": False,
        "cutoff": "2024-07-17",
        "documents": documents,
    }
    path = tmp_path / "public_recipe.json"
    path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")

    result = acquire_mod.acquire_uspto_guidance_pdfs(fixture_path=path)
    assert result.source_kind == "uspto-guidance-package-recipe"
    assert result.receipt["hash_verified"] == len(documents)
    assert len(result.manifest.inventory) == len(documents)
    for entry in result.manifest.inventory:
        assert entry.sha256
        assert entry.extraction is not None


def test_guidance_never_elevated_to_binding_law(acquisition) -> None:
    assert acquisition.manifest.is_binding is False
    assert acquisition.manifest.authority_tier == "guidance"
    for entry in acquisition.manifest.inventory:
        assert entry.is_binding is False
        assert entry.authority_tier == "guidance"
