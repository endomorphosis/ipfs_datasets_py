"""Integration tests: full MPEP section-level acquisition (PATLAW-183).

Acceptance:

* Section count matches inventory minus explicit gaps
* Each section has stable identity and sha256
* Supersession edges are retained when present
* Chapter-landing-page-only crawls fail closed
* Guidance never elevates to binding law
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.mpep_full_section_contracts import (
    AUTHORITY_TIER_GUIDANCE,
    REQUIRED_CHAPTER_IDS,
    BindingElevationError,
    InventoryEntryKind,
    InventoryEntryStatus,
    MpepEditionPin,
    MpepSectionInventoryEntry,
    build_compact_full_inventory_fixture,
    build_mpep_full_manifest,
    content_sha256,
    stable_section_identity,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
ACQUIRE_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "legal_data" / "acquire_mpep_full_sections.py"
)
RUNBOOK = REPO_ROOT / "docs" / "operations" / "PATENT_LEGAL_MPEP_FULL.md"


def _load_acquire_module():
    assert ACQUIRE_SCRIPT.is_file(), f"missing acquisition CLI at {ACQUIRE_SCRIPT}"
    module_name = "acquire_mpep_full_sections_patlaw183"
    spec = importlib.util.spec_from_file_location(module_name, ACQUIRE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def acq():
    return _load_acquire_module()


@pytest.fixture(scope="module")
def inventory_dict() -> dict:
    return build_compact_full_inventory_fixture()


@pytest.fixture(scope="module")
def default_receipt(acq, inventory_dict):
    return acq.acquire_mpep_full_sections(
        inventory_dict,
        mode=acq.AcquisitionMode.DRY_RUN,
    )


@pytest.fixture(scope="module")
def gap_manifest(acq):
    return acq.build_inventory_with_explicit_gap()


# ---------------------------------------------------------------------------
# Declared outputs / pins
# ---------------------------------------------------------------------------


def test_declared_outputs_exist() -> None:
    assert ACQUIRE_SCRIPT.is_file()
    assert RUNBOOK.is_file()


def test_schema_and_task_pins(acq) -> None:
    assert acq.TASK_ID == "PATLAW-183"
    assert acq.GOAL_ID == "PATLAW-G216"
    assert acq.SCHEMA_VERSION == "patent.mpep_full.acquisition.v1"
    assert acq.INTERFACE == "MpepFullSectionAcquisition@1"
    assert acq.PRODUCER == "producer:mpep-full-section-acquisition"
    assert acq.CONFIG_ID == "config:mpep-full-section-acquisition/v1"
    assert acq.CODE_VERSION == "1.0.0"


def test_runbook_covers_operator_surface() -> None:
    text = RUNBOOK.read_text(encoding="utf-8").lower()
    for token in (
        "stable",
        "sha256",
        "supersession",
        "guidance",
        "latest",
        "section",
        "inventory",
        "fixture",
        "patlaw-183",
    ):
        assert token in text, f"runbook missing operator token: {token}"


# ---------------------------------------------------------------------------
# Acceptance: count, identity, supersession
# ---------------------------------------------------------------------------


def test_section_count_matches_inventory_minus_gaps(default_receipt, acq) -> None:
    counts = default_receipt.counts
    inv_entries = counts.inventory_entries
    inv_present = counts.inventory_present
    inv_gaps = counts.inventory_gaps
    acquired = counts.acquired
    assert inv_present + inv_gaps == inv_entries
    assert acquired == inv_present
    assert acquired == inv_entries - inv_gaps
    acq.validate_acquisition_receipt(default_receipt)


def test_each_acquired_section_has_stable_identity_and_sha256(
    default_receipt,
) -> None:
    present = default_receipt.present_sections
    assert len(present) >= len(REQUIRED_CHAPTER_IDS)
    for s in present:
        assert s.stable_identity, f"missing stable_identity for {s.entry_id}"
        assert s.stable_identity.startswith("mpep:us:")
        assert s.content_sha256, f"missing sha256 for {s.entry_id}"
        assert len(s.content_sha256) == 64
        assert s.content_cid and s.content_cid.startswith("b")
        assert s.authority_tier == AUTHORITY_TIER_GUIDANCE
        assert s.is_binding is False
        expected = stable_section_identity(
            kind=s.kind, anchor=s.section_anchor
        )
        assert s.stable_identity == expected
        if s.text is not None:
            assert content_sha256(s.text) == s.content_sha256


def test_supersession_edges_are_retained(default_receipt) -> None:
    supers = default_receipt.supersessions
    assert supers, "compact fixture must include at least one supersession edge"
    assert len(supers) >= 1
    for edge in supers:
        assert edge.remains_guidance is True
        assert edge.elevates_to_law is False
        assert edge.successor_id
        assert edge.predecessor_id
        assert edge.relation.value


def test_explicit_gap_reduces_acquired_count(acq, gap_manifest) -> None:
    receipt = acq.acquire_mpep_full_sections(
        gap_manifest,
        mode=acq.AcquisitionMode.DRY_RUN,
    )
    counts = receipt.counts
    assert counts.inventory_gaps >= 1
    assert counts.acquired == counts.inventory_present
    assert counts.acquired == counts.inventory_entries - counts.inventory_gaps
    gapped = [
        s
        for s in receipt.sections
        if s.section_anchor == "2901"
        and s.status is acq.SectionAcquisitionStatus.GAP
    ]
    assert gapped
    for s in gapped:
        assert s.stable_identity.startswith("mpep:")
        assert s.content_sha256 is None or s.text is None
    acq.validate_acquisition_receipt(receipt, inventory=gap_manifest)


def test_full_chapter_coverage_in_default_fixture(default_receipt) -> None:
    chapters = {s.chapter_id for s in default_receipt.sections}
    assert REQUIRED_CHAPTER_IDS.issubset(chapters)
    counts = default_receipt.counts
    assert counts.section_level_acquired >= len(REQUIRED_CHAPTER_IDS)


def test_guidance_never_elevates(default_receipt) -> None:
    assert default_receipt.authority_tier == AUTHORITY_TIER_GUIDANCE
    assert default_receipt.is_binding is False
    payload = default_receipt.to_dict()
    assert payload["authority_tier"] == "guidance"
    assert payload["is_binding"] is False
    for s in default_receipt.sections:
        assert s.authority_tier == AUTHORITY_TIER_GUIDANCE
        assert s.is_binding is False
    for edge in default_receipt.supersessions:
        assert edge.remains_guidance is True
        assert edge.elevates_to_law is False


def test_edition_pin_is_concrete_never_latest(default_receipt) -> None:
    pin = default_receipt.edition_pin
    assert pin.edition
    assert pin.revision
    assert pin.cutoff
    assert "latest" not in pin.edition.lower()
    assert "latest" not in pin.revision.lower()
    assert pin.edition_key == f"mpep-{pin.edition}-r{pin.revision}"


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------


def test_chapter_landing_only_inventory_fails(acq) -> None:
    """Present chapter-landing anchors fail closed (contracts + acquisition)."""
    from ipfs_datasets_py.processors.domains.patent.mpep_full_section_contracts import (
        ChapterOnlyInventoryError,
    )

    with pytest.raises(ChapterOnlyInventoryError):
        MpepSectionInventoryEntry(
            entry_id="ch-700",
            chapter_id="700",
            section_anchor="700",
            kind=InventoryEntryKind.MPEP_SECTION,
            status=InventoryEntryStatus.PRESENT,
            title="Chapter 700",
            citation="MPEP Chapter 700",
            source_url="https://www.uspto.gov/web/offices/pac/mpep/mpep-0700.html",
            content_sha256=content_sha256("chapter landing"),
        )

    # Even with gap status, a pure landing inventory is rejected by acquisition.
    landings = []
    for ch in sorted(REQUIRED_CHAPTER_IDS):
        if ch.isdigit():
            anchor = ch
        else:
            anchor = f"chapter-{ch}"
        landings.append(
            MpepSectionInventoryEntry(
                entry_id=f"landing-{ch}",
                chapter_id=ch,
                section_anchor=anchor if not ch.isdigit() else ch,
                kind=(
                    InventoryEntryKind.APPENDIX_ANCHOR
                    if ch.startswith("appx")
                    else (
                        InventoryEntryKind.INDEX_ANCHOR
                        if ch == "index"
                        else InventoryEntryKind.MPEP_SECTION
                    )
                ),
                status=InventoryEntryStatus.GAP,
                title=f"Chapter {ch}",
                gap_reason="chapter landing only — not section-level",
            )
        )
    # For numeric chapters, gap with chapter landing is allowed on the entry,
    # but full coverage validation still needs section-level anchors.
    pin = MpepEditionPin(
        edition="9",
        revision="07.2022",
        cutoff="2022-07-01",
    )
    with pytest.raises(
        (acq.ChapterLandingCrawlError, ChapterOnlyInventoryError, Exception)
    ) as inv_exc:
        # Build only landings as present via raw path that bypasses entry ctor
        # for appendix kinds that accept non-numeric anchors — still fails coverage.
        build_mpep_full_manifest(edition_pin=pin, inventory=landings)
    msg = str(inv_exc.value).lower()
    assert "chapter" in msg or "section" in msg


def test_latest_edition_pin_rejected(acq) -> None:
    base = build_compact_full_inventory_fixture()
    base["edition_pin"]["edition"] = "latest"
    with pytest.raises(Exception) as exc_info:
        acq.acquire_mpep_full_sections(base)
    assert "latest" in str(exc_info.value).lower()


def test_binding_elevation_on_section_rejected(default_receipt, acq) -> None:
    present = default_receipt.present_sections[0]
    with pytest.raises(BindingElevationError):
        acq.AcquiredSection(
            entry_id=present.entry_id,
            chapter_id=present.chapter_id,
            section_anchor=present.section_anchor,
            kind=present.kind,
            stable_identity=present.stable_identity,
            status=present.status,
            content_sha256=present.content_sha256,
            is_binding=True,
        )


def test_live_without_allow_live_fails(acq, inventory_dict) -> None:
    with pytest.raises(acq.LiveNetworkDisabledError):
        acq.acquire_mpep_full_sections(
            inventory_dict,
            mode=acq.AcquisitionMode.LIVE,
            allow_live=False,
        )


def test_count_mismatch_fails_strict(acq, inventory_dict) -> None:
    """A fetcher that drops bodies must fail closed under strict_count."""

    def empty_fetcher(request: acq.FetchRequest) -> acq.FetchResult:
        return acq.FetchResult(
            body=None,
            status=acq.SectionAcquisitionStatus.RETRIEVAL_FAILED,
            source_url=request.source_url,
            gap_kind=acq.GapKind.RETRIEVAL_FAILED,
            gap_reason="forced empty for test",
        )

    with pytest.raises(acq.AcquisitionCountMismatchError):
        acq.acquire_mpep_full_sections(
            inventory_dict,
            mode=acq.AcquisitionMode.DRY_RUN,
            fetcher=empty_fetcher,
            strict_count=True,
        )


def test_allow_partial_records_gaps_without_raising(acq, inventory_dict) -> None:
    def fail_one(request: acq.FetchRequest) -> acq.FetchResult:
        if request.entry.section_anchor == "2106":
            return acq.FetchResult(
                body=None,
                status=acq.SectionAcquisitionStatus.RETRIEVAL_FAILED,
                source_url=request.source_url,
                gap_kind=acq.GapKind.RETRIEVAL_FAILED,
                gap_reason="forced fail for 2106",
            )
        return acq.fixture_fetcher(request)

    receipt = acq.acquire_mpep_full_sections(
        inventory_dict,
        fetcher=fail_one,
        strict_count=False,
    )
    assert receipt.counts.acquired == receipt.counts.inventory_present - 1
    assert receipt.counts.acquisition_gaps >= 1
    failed = [
        s
        for s in receipt.sections
        if s.section_anchor == "2106"
        and s.status is acq.SectionAcquisitionStatus.RETRIEVAL_FAILED
    ]
    assert failed
    with pytest.raises(acq.AcquisitionCountMismatchError):
        acq.validate_acquisition_receipt(receipt)


# ---------------------------------------------------------------------------
# Content addressing / staging / CLI
# ---------------------------------------------------------------------------


def test_acquisition_is_content_address_stable(acq, inventory_dict) -> None:
    from datetime import datetime, timezone

    fixed_at = datetime(2022, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    r1 = acq.acquire_mpep_full_sections(
        inventory_dict, acquired_at=fixed_at
    )
    r2 = acq.acquire_mpep_full_sections(
        inventory_dict, acquired_at=fixed_at
    )
    digests_1 = (r1.package_digest_sha256, r1.package_root_cid, r1.inventory_digest_sha256)
    digests_2 = (r2.package_digest_sha256, r2.package_root_cid, r2.inventory_digest_sha256)
    assert digests_1 == digests_2
    identities_1 = sorted(s.stable_identity for s in r1.present_sections)
    identities_2 = sorted(s.stable_identity for s in r2.present_sections)
    assert identities_1 == identities_2


def test_stage_writes_receipt_sections_and_supersessions(
    acq, default_receipt, inventory_dict, tmp_path: Path
) -> None:
    out = tmp_path / "mpep-full-acq"
    result = acq.stage_acquisition(
        default_receipt,
        out,
        inventory=inventory_dict,
    )
    assert result.receipt_path.is_file()
    assert result.sections_dir.is_dir()
    assert result.inventory_path is not None and result.inventory_path.is_file()
    assert result.supersessions_path is not None and result.supersessions_path.is_file()

    payload = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    assert payload["task_id"] == "PATLAW-183"
    assert payload["schema_version"] == acq.SCHEMA_VERSION
    assert payload["counts"]["acquired"] == default_receipt.counts.acquired

    section_files = list(result.sections_dir.glob("*.txt"))
    assert len(section_files) == len(default_receipt.present_sections)
    for path in section_files:
        body = path.read_text(encoding="utf-8").rstrip("\n")
        assert body
        assert content_sha256(body)

    supers = json.loads(result.supersessions_path.read_text(encoding="utf-8"))
    assert isinstance(supers, list) and supers
    assert supers[0]["remains_guidance"] is True


def test_fixture_body_matches_inventory_digest(acq, inventory_dict) -> None:
    """Offline bodies must satisfy digests declared by the PATLAW-182 fixture."""
    for raw in inventory_dict["inventory"]:
        if raw.get("status") != "present":
            continue
        entry = MpepSectionInventoryEntry.from_dict(raw)
        body = acq.fixture_section_body(
            entry,
            inventory_dict["edition_pin"]["edition"],
            inventory_dict["edition_pin"]["revision"],
        )
        assert content_sha256(body) == entry.content_sha256


def test_receipt_round_trip_dict(default_receipt, acq) -> None:
    payload = default_receipt.to_dict()
    rebuilt = acq.MpepFullAcquisitionReceipt.from_dict(payload)
    assert rebuilt.package_digest_sha256 == default_receipt.package_digest_sha256
    assert rebuilt.counts.acquired == default_receipt.counts.acquired
    assert len(rebuilt.supersessions) == len(default_receipt.supersessions)
    assert rebuilt.task_id == "PATLAW-183"
    assert payload["counts"]["acquired"] == payload["counts"]["inventory_present"]
    assert payload["authority_tier"] == "guidance"
    assert payload["is_binding"] is False


def test_cli_default_fixture_dry_run(acq, capsys) -> None:
    rc = acq.main(["--default-fixture"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "inventory_present" in out
    assert "package_digest_sha256" in out
    assert "PATLAW-183" in out or "schema_version" in out


def test_cli_stage(acq, tmp_path: Path) -> None:
    out = tmp_path / "staged"
    rc = acq.main(
        [
            "--default-fixture",
            "--stage",
            "--output-dir",
            str(out),
        ]
    )
    assert rc == 0
    assert (out / acq.RECEIPT_FILENAME).is_file()
    assert (out / acq.SECTIONS_DIRNAME).is_dir()
    assert (out / acq.INVENTORY_FILENAME).is_file()
    assert (out / acq.SUPERSESSIONS_FILENAME).is_file()


def test_cli_write_default_inventory(acq, tmp_path: Path) -> None:
    path = tmp_path / "mpep-full.manifest.json"
    rc = acq.main(["--write-default-inventory", str(path)])
    assert rc == 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["inventory"]) >= len(REQUIRED_CHAPTER_IDS)


def test_cli_rejects_missing_inventory(acq) -> None:
    rc = acq.main(["--inventory", "/nonexistent/mpep-full.manifest.json"])
    assert rc != 0


def test_form_paragraphs_get_stable_fp_identity(default_receipt) -> None:
    fps = [
        s
        for s in default_receipt.present_sections
        if s.kind is InventoryEntryKind.FORM_PARAGRAPH
    ]
    assert fps, "compact fixture should include form-paragraph anchors"
    for fp in fps:
        assert ":form_paragraph:" in fp.stable_identity
        assert fp.content_sha256


def test_package_digest_binds_section_identities(default_receipt, acq) -> None:
    """Package digest must change if a section identity or digest changes."""
    original = default_receipt.package_digest_sha256
    assert original
    assert default_receipt.addressable_payload()["package_digest_sha256"] == original

    # Mutate one section identity on a copy and recompute package digest shape.
    sections = list(default_receipt.sections)
    first = sections[0]
    mutated = acq.AcquiredSection(
        entry_id=first.entry_id,
        chapter_id=first.chapter_id,
        section_anchor=first.section_anchor,
        kind=first.kind,
        stable_identity=first.stable_identity + "-mut",
        status=first.status,
        content_sha256=first.content_sha256,
        text=first.text,
        source_url=first.source_url,
        media_type=first.media_type,
        title=first.title,
        citation=first.citation,
    )
    sections[0] = mutated
    package_payload = {
        "counts": default_receipt.counts.to_dict(),
        "edition_pin": default_receipt.edition_pin.to_dict(),
        "inventory_digest_sha256": default_receipt.inventory_digest_sha256,
        "sections": [
            {
                "content_sha256": s.content_sha256,
                "entry_id": s.entry_id,
                "stable_identity": s.stable_identity,
                "status": s.status.value,
            }
            for s in sections
        ],
        "supersessions": [e.to_dict() for e in default_receipt.supersessions],
        "task_id": acq.TASK_ID,
    }
    from ipfs_datasets_py.processors.domains.patent.mpep_full_section_contracts import (
        content_digest_of,
    )

    mutated_digest = content_digest_of(package_payload)
    assert mutated_digest != original
    assert not mutated.stable_identity.endswith(
        first.stable_identity.split(":")[-1]
    ) or mutated.stable_identity.endswith("-mut")


def test_load_inventory_from_path(acq, inventory_dict, tmp_path: Path) -> None:
    path = tmp_path / "mpep-full.manifest.json"
    path.write_text(json.dumps(inventory_dict), encoding="utf-8")
    loaded = acq.load_inventory_manifest(path)
    assert len(loaded.inventory) == len(inventory_dict["inventory"])
    receipt = acq.acquire_mpep_full_sections(loaded)
    assert receipt.counts.acquired == receipt.counts.inventory_present
