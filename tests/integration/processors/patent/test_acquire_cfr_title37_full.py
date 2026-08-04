"""Integration tests: full annual CFR Title 37 acquisition (PATLAW-181).

Acceptance:

* Full inventory is present for the pinned edition
* Each section has text or an explicit gap record
* Package sha256 / CID bind the official annual acquisition
* eCFR-only partial crawls do not complete this task
* Offline bounded GovInfo fixture is sufficient for CI (no network / no Hub)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.cfr_title37_full_contracts import (
    MANIFEST_FILENAME,
    SCHEMA_VERSION,
    TITLE37_PARTS,
    EditionIdentity,
    IncompleteInventoryError,
    SectionPresence,
    UnpinnedLatestError,
    title37_section_count,
    validate_manifest,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "acquire_cfr_title37_full.py"
)
_DEFAULT_FIXTURE = (
    _REPO_ROOT
    / "tests"
    / "fixtures"
    / "legal_data"
    / "patent_authorities"
    / "cfr"
    / "cfr_annual_recipe.json"
)


def _load_acquire_module():
    assert _SCRIPT_PATH.is_file(), f"missing acquisition CLI at {_SCRIPT_PATH}"
    module_name = "acquire_cfr_title37_full_patlaw181"
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
    return acquire_mod.acquire_cfr_title37_full(
        fixture_path=_DEFAULT_FIXTURE,
        stage=False,
        require_full_catalog=True,
    )


# ---------------------------------------------------------------------------
# Fixture / pins
# ---------------------------------------------------------------------------


def test_default_fixture_is_official_annual_govinfo_not_ecfr_only() -> None:
    assert _DEFAULT_FIXTURE.is_file()
    payload = json.loads(_DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    assert payload["package"]["package_id"] == "CFR-2024-title37"
    assert payload["package"]["provider"] == "govinfo"
    assert payload["package"]["content_sha256"]
    # eCFR presentation may be linked but must remain separate.
    assert payload.get("ecfr_presentation_sha256")
    assert (
        payload["ecfr_presentation_sha256"]
        != payload["package"]["content_sha256"]
    )


def test_acquire_module_pins(acquire_mod) -> None:
    assert acquire_mod.ACQUIRE_TASK_ID == "PATLAW-181"
    assert acquire_mod.ACQUIRE_GOAL_ID == "PATLAW-G215"
    assert acquire_mod.ACQUIRE_SCHEMA_VERSION.startswith(
        "patent.cfr_title37_full.acquisition"
    )
    assert acquire_mod.RECEIPT_FILENAME.endswith(".json")
    assert Path(acquire_mod.default_fixture_path()).is_file()


# ---------------------------------------------------------------------------
# Full inventory + text-or-gap
# ---------------------------------------------------------------------------


def test_full_inventory_for_pinned_edition(acquisition) -> None:
    manifest = acquisition.manifest
    assert manifest.edition_identity.package_id == "CFR-2024-title37"
    assert manifest.edition_identity.year == "2024"
    assert manifest.edition_identity.authority_tier == "official-base"
    assert "latest" not in manifest.edition_identity.package_id.lower()
    assert "latest" not in manifest.edition_identity.edition.lower()

    catalog_n = title37_section_count()
    assert catalog_n >= 500
    assert len(manifest.inventory) >= catalog_n
    assert manifest.counts is not None
    assert manifest.counts.total_sections == len(manifest.inventory)
    assert manifest.counts.total_parts == len(TITLE37_PARTS)

    # Full catalog coverage contract.
    manifest.assert_full_catalog_coverage()
    validate_manifest(manifest, require_full_catalog=True)


def test_every_section_has_text_or_explicit_gap(acquisition) -> None:
    manifest = acquisition.manifest
    inventory_gaps = {
        e.section for e in manifest.inventory if e.presence is SectionPresence.GAP
    }
    gap_record_sections = {g.section for g in manifest.gaps}
    assert inventory_gaps == gap_record_sections

    present = [
        e for e in manifest.inventory if e.presence is SectionPresence.PRESENT
    ]
    gaps = [e for e in manifest.inventory if e.presence is SectionPresence.GAP]
    assert present, "bounded fixture must yield at least one present section"
    assert gaps, "bounded fixture must leave explicit gaps for missing granules"
    assert len(present) + len(gaps) == len(manifest.inventory)

    # Present rows bind content digests; gap rows must not.
    for entry in present:
        assert entry.content_sha256
        assert len(entry.content_sha256) == 64
        assert entry.section in acquisition.section_texts
        assert acquisition.section_texts[entry.section].strip()

    for entry in gaps:
        assert entry.content_sha256 is None
        assert entry.section not in acquisition.section_texts

    for gap in manifest.gaps:
        assert gap.reason
        assert gap.section
        assert gap.stable_id


def test_package_sha256_and_cid_bind_acquisition(acquisition) -> None:
    binding = acquisition.manifest.package_binding
    assert binding.package_id == "CFR-2024-title37"
    assert binding.package_digest_sha256
    assert len(binding.package_digest_sha256) == 64
    assert binding.package_root_cid
    assert binding.package_root_cid.startswith("b")
    assert len(binding.package_root_cid) >= 20

    # CID is a deterministic function of the package digest.
    assert acquisition.package_root_cid == binding.package_root_cid
    assert acquisition.package_digest_sha256 == binding.package_digest_sha256

    fixture = json.loads(_DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    assert binding.package_digest_sha256 == fixture["package"]["content_sha256"]
    assert binding.source_url
    assert "govinfo.gov" in binding.source_url
    assert "ecfr.gov" not in (binding.source_url or "")


def test_receipt_binds_package_and_rejects_hub_upload(acquisition) -> None:
    receipt = dict(acquisition.receipt)
    assert receipt["task_id"] == "PATLAW-181"
    assert receipt["goal_id"] == "PATLAW-G215"
    assert receipt["package_id"] == "CFR-2024-title37"
    assert receipt["package_digest_sha256"] == acquisition.package_digest_sha256
    assert receipt["package_root_cid"] == acquisition.package_root_cid
    assert receipt["full_inventory"] is True
    assert receipt["ecfr_only_rejected"] is True
    assert receipt["hub_upload"] is False
    assert receipt["source_kind"] == "govinfo-annual-fixture"
    assert receipt["authority_tier"] == "official-base"
    assert receipt["present_sections"] >= 1
    assert receipt["gap_sections"] >= 1
    assert receipt["catalog_section_count"] == title37_section_count()


# ---------------------------------------------------------------------------
# eCFR-only fail-closed
# ---------------------------------------------------------------------------


def test_ecfr_only_flag_is_rejected(acquire_mod) -> None:
    with pytest.raises(acquire_mod.EcfrOnlyAcquisitionError):
        acquire_mod.acquire_cfr_title37_full(ecfr_only=True)


def test_ecfr_only_payload_without_package_is_rejected(acquire_mod) -> None:
    payload = {
        "source_kind": "ecfr-only",
        "ecfr_presentation": {
            "provider": "ecfr",
            "source_id": "ecfr:title-37:as-of-2024-07-01",
            "artifact_sha256": "c" * 64,
            "source_url": "https://www.ecfr.gov/current/title-37",
        },
        "ecfr_presentation_sha256": "c" * 64,
    }
    with pytest.raises(acquire_mod.EcfrOnlyAcquisitionError):
        acquire_mod.assert_not_ecfr_only(payload)

    with pytest.raises(acquire_mod.EcfrOnlyAcquisitionError):
        acquire_mod.acquire_from_ecfr_only_payload(payload)


def test_ecfr_presentation_without_annual_package_is_rejected(acquire_mod) -> None:
    payload = {
        "ecfr_presentation_sha256": "a" * 64,
        "sections": [{"section": "1.56", "text_excerpt": "not enough"}],
    }
    with pytest.raises(acquire_mod.EcfrOnlyAcquisitionError):
        acquire_mod.assert_not_ecfr_only(payload)


def test_cli_reject_ecfr_only_exits_nonzero(acquire_mod) -> None:
    code = acquire_mod.main(["--reject-ecfr-only"])
    assert code == 2


# ---------------------------------------------------------------------------
# Identity / year pins
# ---------------------------------------------------------------------------


def test_unpinned_latest_year_is_rejected(acquire_mod) -> None:
    with pytest.raises((UnpinnedLatestError, Exception)):
        acquire_mod.acquire_cfr_title37_full(
            year="latest",
            fixture_path=_DEFAULT_FIXTURE,
        )


def test_year_mismatch_against_fixture_is_rejected(acquire_mod) -> None:
    with pytest.raises(Exception) as excinfo:
        acquire_mod.acquire_cfr_title37_full(
            year=2020,
            fixture_path=_DEFAULT_FIXTURE,
        )
    # MissingEditionIdentityError or similar year mismatch.
    assert "2020" in str(excinfo.value) or "year" in str(excinfo.value).lower()


def test_live_mode_fails_closed_without_network_client(acquire_mod) -> None:
    with pytest.raises(acquire_mod.LiveAcquisitionUnavailableError):
        acquire_mod.acquire_cfr_title37_full(live=True)


# ---------------------------------------------------------------------------
# Staging + CLI
# ---------------------------------------------------------------------------


def test_stage_writes_manifest_receipt_and_section_texts(
    acquire_mod, tmp_path: Path
) -> None:
    out = tmp_path / "cfr-title37-full"
    result = acquire_mod.acquire_cfr_title37_full(
        fixture_path=_DEFAULT_FIXTURE,
        output_dir=out,
        stage=True,
    )
    assert result.output_dir == out
    manifest_path = out / MANIFEST_FILENAME
    receipt_path = out / acquire_mod.RECEIPT_FILENAME
    meta_path = out / acquire_mod.PACKAGE_META_FILENAME
    sections_dir = out / acquire_mod.SECTIONS_DIRNAME

    assert manifest_path.is_file()
    assert receipt_path.is_file()
    assert meta_path.is_file()
    assert sections_dir.is_dir()

    staged = json.loads(manifest_path.read_text(encoding="utf-8"))
    validated = validate_manifest(staged, require_full_catalog=True)
    assert validated.package_binding.package_digest_sha256 == (
        result.package_digest_sha256
    )
    assert validated.package_binding.package_root_cid == result.package_root_cid

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["task_id"] == "PATLAW-181"
    assert receipt["package_digest_sha256"] == result.package_digest_sha256

    # One text file per present section.
    text_files = sorted(sections_dir.glob("*.txt"))
    assert len(text_files) == len(result.section_texts)
    assert len(text_files) >= 1
    for path in text_files:
        assert path.read_text(encoding="utf-8").strip()


def test_cli_default_fixture_dry_run(acquire_mod, capsys) -> None:
    code = acquire_mod.main(
        ["--default-fixture", "--year", "2024", "--no-print-summary"]
    )
    assert code == 0


def test_cli_default_fixture_stage_and_validate(
    acquire_mod, tmp_path: Path, capsys
) -> None:
    out = tmp_path / "staged"
    code = acquire_mod.main(
        [
            "--default-fixture",
            "--stage",
            "--output-dir",
            str(out),
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "CFR-2024-title37" in captured.out
    assert "package_digest_sha256" in captured.out
    assert "package_root_cid" in captured.out
    assert "ecfr_only_rejected" in captured.out

    code = acquire_mod.main(
        ["--validate-manifest", str(out / MANIFEST_FILENAME)]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "manifest_ok: true" in captured.out


def test_cli_live_exits_nonzero(acquire_mod) -> None:
    code = acquire_mod.main(["--default-fixture", "--live"])
    assert code == 2


def test_cid_for_sha256_is_stable(acquire_mod) -> None:
    digest = "29df01158775bcceb32c24148647b8ad4ba4477c5697807f143123b0266e5d80"
    cid_a = acquire_mod.cid_for_sha256(digest)
    cid_b = acquire_mod.cid_for_sha256(digest)
    assert cid_a == cid_b
    assert cid_a.startswith("b")
    assert len(cid_a) >= 20


def test_schema_version_on_manifest(acquisition) -> None:
    assert acquisition.manifest.schema_version == SCHEMA_VERSION
    assert acquisition.manifest.mode.value in {"acquire", "stage", "dry_run"}


def test_incomplete_inventory_is_not_accepted_as_full(
    acquire_mod, acquisition
) -> None:
    """Partial inventories without full catalog coverage fail closed."""

    # Build a deliberately incomplete inventory and ensure validation rejects it.
    identity = EditionIdentity.for_year(2024)
    partial_entries = list(acquisition.manifest.inventory)[:3]
    from ipfs_datasets_py.processors.domains.patent.cfr_title37_full_contracts import (
        CfrTitle37FullManifest,
        PackageBinding,
        build_gap_records_for_inventory,
    )

    inventory = tuple(partial_entries)
    # Force all present to avoid gap consistency issues for this unit of work.
    # Use the acquisition binding shape.
    binding = acquisition.manifest.package_binding
    with pytest.raises((IncompleteInventoryError, Exception)):
        manifest = CfrTitle37FullManifest(
            edition_identity=identity,
            inventory=inventory,
            package_binding=PackageBinding(
                package_id=binding.package_id,
                package_digest_sha256=binding.package_digest_sha256,
                package_root_cid=binding.package_root_cid,
            ),
            gaps=build_gap_records_for_inventory(inventory),
        )
        manifest.assert_full_catalog_coverage()
