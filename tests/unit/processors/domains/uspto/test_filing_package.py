"""Unit tests for rule- and prior-art-aware filing package compiler (PATLAW-153).

Acceptance focus:
  - Any material input change invalidates approval
  - Missing/stale mandatory rules, unresolved prior-art coverage, digest
    mismatch, or required human confirmation blocks validated state
  - Output distinguishes proposed metadata, original files, rendered
    derivatives, and operator checklist
  - Never signs, pays, files, certifies, or claims Patent Center validation
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.filing_package import (
    FILING_PACKAGE_DISCLAIMER,
    FILING_PACKAGE_SCHEMA_VERSION,
    FORBIDDEN_PACKAGE_ACTIONS,
    MANDATORY_CHECKLIST_CATEGORIES,
    OUTPUT_KIND_FILING_PACKAGE,
    ChecklistCategory,
    DrawingsInventoryItem,
    FilingPackageCompiler,
    FilingPackageError,
    FilingPackageInput,
    FilingPackageManifest,
    FilingPackageReasonCode,
    FilingPackageState,
    ForbiddenPackageActionError,
    MediaKind,
    OperatorChecklistItem,
    OriginalFileRole,
    PackageApprovalInvalidatedError,
    PackageArtifactFamily,
    PackageFileEntry,
    PackageNotValidatedError,
    PackageValidationBlockedError,
    PriorArtCoverageBinding,
    ProposedAdsField,
    RulePackBinding,
    RulePackStatus,
    ValidationBlockReason,
    assert_action_allowed,
    compile_filing_package,
    confirm_checklist_items,
    default_mandatory_checklist,
    evaluate_validation_blocks,
    is_forbidden_action,
    package_inputs_match,
    sha256_hex,
    validate_filing_package,
)

# ---------------------------------------------------------------------------
# Paths / fixed digests
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[5]
_GOLDEN_PATH = (
    _REPO_ROOT / "tests/fixtures/uspto/filing_package/golden_manifest.json"
)

_DOCX_DIGEST = sha256_hex(b"patlaw-153-spec-docx-v1")
_CLAIMS_DIGEST = sha256_hex(b"patlaw-153-claims-docx-v1")
_PDF_DIGEST = sha256_hex(b"patlaw-153-spec-pdf-render-v1")
_DRAWINGS_DIGEST = sha256_hex(b"patlaw-153-drawings-pdf-v1")
_PACK_DIGEST = sha256_hex(b"patlaw-153-baseline-pack-v1")
_PACK_DIGEST_STALE = sha256_hex(b"patlaw-153-baseline-pack-stale")
_COVERAGE_DIGEST = sha256_hex(b"patlaw-153-prior-art-coverage-v1")
_COVERAGE_DIGEST_STALE = sha256_hex(b"patlaw-153-prior-art-coverage-stale")
_PORTFOLIO_DIGEST = sha256_hex(b"patlaw-153-portfolio-facts-v1")
_DATES_DIGEST = sha256_hex(b"patlaw-153-candidate-dates-v1")
_DRAWING_SHEET_DIGEST = sha256_hex(b"patlaw-153-fig1-sheet")

_seq: Iterator[int] = itertools.count(1)


def _reset() -> None:
    global _seq
    _seq = itertools.count(1)


def _id_factory() -> str:
    return f"{next(_seq):04d}"


def _compiler() -> FilingPackageCompiler:
    _reset()
    return FilingPackageCompiler(id_factory=_id_factory)


def _active_rule_pack(**overrides: Any) -> RulePackBinding:
    base: dict[str, Any] = {
        "pack_id": "uspto.baseline-filing-obligations",
        "pack_version": "1.0.0",
        "pack_digest": _PACK_DIGEST,
        "status": RulePackStatus.ACTIVE,
        "source_digests_recorded": True,
        "human_approval_recorded": True,
        "expected_pack_digest": _PACK_DIGEST,
        "rule_ids": ("rule:utility:spec", "rule:utility:claims", "rule:utility:ads"),
    }
    base.update(overrides)
    return RulePackBinding(**base)


def _resolved_prior_art(**overrides: Any) -> PriorArtCoverageBinding:
    base: dict[str, Any] = {
        "declaration_id": "coverage:patlaw-153-1",
        "coverage_digest": _COVERAGE_DIGEST,
        "coverage_complete": True,
        "human_signoff_recorded": True,
        "unresolved_gap_ids": (),
        "blocking_reason_codes": (),
        "expected_coverage_digest": _COVERAGE_DIGEST,
        "ids_queue_digest": sha256_hex(b"ids-queue-v1"),
    }
    base.update(overrides)
    return PriorArtCoverageBinding(**base)


def _original_files() -> tuple[PackageFileEntry, ...]:
    return (
        PackageFileEntry(
            file_id="file:spec-docx",
            family=PackageArtifactFamily.ORIGINAL_FILE,
            role=OriginalFileRole.SPECIFICATION,
            media_kind=MediaKind.DOCX,
            content_digest=_DOCX_DIGEST,
            filename="specification.docx",
            source_root="vault://tenant-a/matters/m1/originals",
            byte_size=12000,
        ),
        PackageFileEntry(
            file_id="file:claims-docx",
            family=PackageArtifactFamily.ORIGINAL_FILE,
            role=OriginalFileRole.CLAIMS,
            media_kind=MediaKind.DOCX,
            content_digest=_CLAIMS_DIGEST,
            filename="claims.docx",
            source_root="vault://tenant-a/matters/m1/originals",
            byte_size=4000,
        ),
        PackageFileEntry(
            file_id="file:drawings-pdf",
            family=PackageArtifactFamily.ORIGINAL_FILE,
            role=OriginalFileRole.DRAWINGS,
            media_kind=MediaKind.PDF,
            content_digest=_DRAWINGS_DIGEST,
            filename="drawings.pdf",
            source_root="vault://tenant-a/matters/m1/originals",
            byte_size=8000,
        ),
        PackageFileEntry(
            file_id="file:spec-pdf-render",
            family=PackageArtifactFamily.RENDERED_DERIVATIVE,
            role=OriginalFileRole.SPECIFICATION,
            media_kind=MediaKind.PDF,
            content_digest=_PDF_DIGEST,
            filename="specification.converted.pdf",
            source_root="vault://tenant-a/matters/m1/renders",
            derived_from_file_id="file:spec-docx",
            byte_size=15000,
        ),
    )


def _ads_fields() -> tuple[ProposedAdsField, ...]:
    return (
        ProposedAdsField(
            field_id="ads:title",
            field_name="invention_title",
            proposed_value="Temperature Sensing Apparatus",
            origin="operator_supplied",
        ),
        ProposedAdsField(
            field_id="ads:entity",
            field_name="entity_status",
            proposed_value="small",
            origin="portfolio_projection",
        ),
        ProposedAdsField(
            field_id="ads:inventor-1",
            field_name="inventor_1_name",
            proposed_value="Ada Inventor",
            origin="operator_supplied",
        ),
    )


def _drawings() -> tuple[DrawingsInventoryItem, ...]:
    return (
        DrawingsInventoryItem(
            item_id="fig:1",
            figure_label="FIG. 1",
            sheet_number=1,
            description="System overview",
            content_digest=_DRAWING_SHEET_DIGEST,
        ),
        DrawingsInventoryItem(
            item_id="fig:2",
            figure_label="FIG. 2",
            sheet_number=2,
            description="Sensor detail",
        ),
    )


def _ready_input(**overrides: Any) -> FilingPackageInput:
    """Material inputs that can reach validated after checklist confirmation."""
    base: dict[str, Any] = {
        "matter_id": "matter:patlaw-153-1",
        "application_type": "utility",
        "original_files": _original_files(),
        "proposed_ads_fields": _ads_fields(),
        "drawings_inventory": _drawings(),
        "operator_checklist": default_mandatory_checklist(),
        "rule_pack": _active_rule_pack(),
        "prior_art": _resolved_prior_art(),
        "classification": DisclosureClassification.CONFIDENTIAL_APPLICATION,
        "portfolio_fact_digest": _PORTFOLIO_DIGEST,
        "candidate_dates_digest": _DATES_DIGEST,
        "source_roots": (
            "vault://tenant-a/matters/m1/originals",
            "vault://tenant-a/matters/m1/renders",
        ),
        "warnings": ("rendered PDF is derivative of DOCX; DOCX remains authoritative",),
        "labels": {"fixture": "patlaw-153", "channel": "unit"},
        "require_mandatory_checklist_categories": True,
    }
    base.update(overrides)
    return FilingPackageInput(**base)


def _confirmed_input(**overrides: Any) -> FilingPackageInput:
    raw = _ready_input(**overrides)
    return confirm_checklist_items(
        raw,
        confirmed_by="Pat Attorney",
        confirmed_at_utc="2026-03-15T14:00:00Z",
    )


# ---------------------------------------------------------------------------
# Forbidden actions
# ---------------------------------------------------------------------------


class TestForbiddenActions:
    def test_forbidden_set_includes_sign_pay_file_certify(self) -> None:
        for action in (
            "sign",
            "pay",
            "file",
            "submit",
            "mark_submitted",
            "assert_human_certification",
            "claim_patent_center_validation",
            "select_legal_strategy",
            "fabricate_acknowledgement",
        ):
            assert action in FORBIDDEN_PACKAGE_ACTIONS
            assert is_forbidden_action(action)

    def test_assert_action_allowed_raises(self) -> None:
        with pytest.raises(ForbiddenPackageActionError) as exc:
            assert_action_allowed("mark_submitted")
        assert exc.value.code == "forbidden_package_action"
        assert exc.value.action == "mark_submitted"

    def test_compiler_methods_raise(self) -> None:
        c = _compiler()
        for method_name in (
            "sign",
            "pay",
            "file",
            "submit",
            "mark_submitted",
            "assert_human_certification",
            "claim_patent_center_validation",
        ):
            with pytest.raises(ForbiddenPackageActionError):
                getattr(c, method_name)()

    def test_manifest_capability_locks(self) -> None:
        manifest = validate_filing_package(
            _confirmed_input(), id_factory=_id_factory, package_id="pkg:locks"
        )
        assert manifest.is_submitted is False
        assert manifest.can_sign is False
        assert manifest.can_pay is False
        assert manifest.can_file is False
        assert manifest.filing_is_external is True
        assert manifest.certification_asserted is False
        data = manifest.to_dict()
        data["is_submitted"] = True
        data["can_sign"] = True
        data["can_file"] = True
        data["certification_asserted"] = True
        data.pop("content_digest", None)
        revived = FilingPackageManifest.from_dict(data)
        assert revived.is_submitted is False
        assert revived.can_sign is False
        assert revived.can_file is False
        assert revived.certification_asserted is False


# ---------------------------------------------------------------------------
# Distinguishes output families
# ---------------------------------------------------------------------------


class TestArtifactFamilies:
    def test_output_distinguishes_four_families(self) -> None:
        manifest = compile_filing_package(
            _ready_input(), id_factory=_id_factory, package_id="pkg:families"
        )
        data = manifest.to_dict()
        assert "proposed_metadata" in data
        assert "original_files" in data
        assert "rendered_derivatives" in data
        assert "operator_checklist" in data

        families = manifest.distinguished_families()
        assert set(families.keys()) == {
            "proposed_metadata",
            "original_file",
            "rendered_derivative",
            "operator_checklist",
        }

        # Proposed metadata is not filed fact
        assert data["proposed_metadata"]["family"] == "proposed_metadata"
        assert "ads_fields" in data["proposed_metadata"]
        ads_names = {
            f["field_name"] for f in data["proposed_metadata"]["ads_fields"]
        }
        assert "invention_title" in ads_names

        # Originals are DOCX/PDF roots; derivatives are separate
        original_ids = {f["file_id"] for f in data["original_files"]}
        derivative_ids = {f["file_id"] for f in data["rendered_derivatives"]}
        assert "file:spec-docx" in original_ids
        assert "file:claims-docx" in original_ids
        assert "file:spec-pdf-render" in derivative_ids
        assert "file:spec-pdf-render" not in original_ids
        assert all(
            f["family"] == "original_file" for f in data["original_files"]
        )
        assert all(
            f["family"] == "rendered_derivative"
            for f in data["rendered_derivatives"]
        )

        # Operator checklist covers mandatory review categories
        cats = {c["category"] for c in data["operator_checklist"]}
        assert MANDATORY_CHECKLIST_CATEGORIES <= cats

    def test_drawings_inventory_and_source_roots_present(self) -> None:
        manifest = compile_filing_package(
            _ready_input(), id_factory=_id_factory, package_id="pkg:draw"
        )
        assert len(manifest.drawings_inventory) == 2
        assert manifest.drawings_inventory[0].figure_label == "FIG. 1"
        assert "vault://tenant-a/matters/m1/originals" in manifest.source_roots
        assert any("authoritative" in w for w in manifest.warnings)


# ---------------------------------------------------------------------------
# Validation gates (fail-closed)
# ---------------------------------------------------------------------------


class TestValidationGates:
    def test_missing_rules_blocks_validated(self) -> None:
        inp = _confirmed_input(rule_pack=None)
        manifest = validate_filing_package(
            inp, id_factory=_id_factory, package_id="pkg:no-rules"
        )
        assert manifest.state is FilingPackageState.DRAFT
        assert ValidationBlockReason.MISSING_MANDATORY_RULES.value in (
            manifest.block_reasons
        )
        assert not manifest.is_validated

    def test_inactive_rules_block(self) -> None:
        pack = _active_rule_pack(status=RulePackStatus.DRAFT)
        inp = _confirmed_input(rule_pack=pack)
        manifest = validate_filing_package(
            inp, id_factory=_id_factory, package_id="pkg:draft-rules"
        )
        assert ValidationBlockReason.RULE_PACK_NOT_ACTIVE.value in (
            manifest.block_reasons
        )
        assert ValidationBlockReason.MISSING_MANDATORY_RULES.value in (
            manifest.block_reasons
        )

    def test_stale_rules_block(self) -> None:
        pack = _active_rule_pack(
            pack_digest=_PACK_DIGEST_STALE,
            expected_pack_digest=_PACK_DIGEST,
        )
        inp = _confirmed_input(rule_pack=pack)
        manifest = validate_filing_package(
            inp, id_factory=_id_factory, package_id="pkg:stale-rules"
        )
        assert ValidationBlockReason.STALE_MANDATORY_RULES.value in (
            manifest.block_reasons
        )
        assert ValidationBlockReason.DIGEST_MISMATCH.value in manifest.block_reasons
        assert FilingPackageReasonCode.RULES_STALE.value in manifest.reason_codes

    def test_missing_prior_art_blocks(self) -> None:
        inp = _confirmed_input(prior_art=None)
        manifest = validate_filing_package(
            inp, id_factory=_id_factory, package_id="pkg:no-pa"
        )
        assert ValidationBlockReason.UNRESOLVED_PRIOR_ART.value in (
            manifest.block_reasons
        )
        assert ValidationBlockReason.PRIOR_ART_SIGNOFF_MISSING.value in (
            manifest.block_reasons
        )

    def test_unresolved_prior_art_blocks(self) -> None:
        pa = _resolved_prior_art(
            coverage_complete=False,
            unresolved_gap_ids=("gap:foreign-patents",),
            human_signoff_recorded=False,
            blocking_reason_codes=("missing_human_coverage_acknowledgment",),
        )
        inp = _confirmed_input(prior_art=pa)
        manifest = validate_filing_package(
            inp, id_factory=_id_factory, package_id="pkg:unresolved-pa"
        )
        assert ValidationBlockReason.UNRESOLVED_PRIOR_ART.value in (
            manifest.block_reasons
        )
        assert FilingPackageReasonCode.PRIOR_ART_UNRESOLVED.value in (
            manifest.reason_codes
        )

    def test_stale_prior_art_digest_blocks(self) -> None:
        pa = _resolved_prior_art(
            coverage_digest=_COVERAGE_DIGEST_STALE,
            expected_coverage_digest=_COVERAGE_DIGEST,
        )
        inp = _confirmed_input(prior_art=pa)
        manifest = validate_filing_package(
            inp, id_factory=_id_factory, package_id="pkg:stale-pa"
        )
        assert ValidationBlockReason.DIGEST_MISMATCH.value in manifest.block_reasons
        assert ValidationBlockReason.UNRESOLVED_PRIOR_ART.value in (
            manifest.block_reasons
        )

    def test_open_human_confirmation_blocks_validated(self) -> None:
        inp = _ready_input()  # checklist unconfirmed
        manifest = validate_filing_package(
            inp, id_factory=_id_factory, package_id="pkg:open-confirm"
        )
        assert manifest.state is FilingPackageState.DRAFT
        assert ValidationBlockReason.HUMAN_CONFIRMATION_REQUIRED.value in (
            manifest.block_reasons
        )
        assert manifest.open_confirmation_ids
        assert all(
            cid.startswith("check:") for cid in manifest.open_confirmation_ids
        )

    def test_confirmation_digest_mismatch_blocks(self) -> None:
        wrong = sha256_hex(b"wrong-package-digest")
        checklist = default_mandatory_checklist(
            confirmed=True,
            confirmed_by="Pat Attorney",
            confirmed_at_utc="2026-03-15T14:00:00Z",
            bound_package_digest=wrong,
        )
        inp = _ready_input(operator_checklist=checklist)
        blocks, open_ids, _ = evaluate_validation_blocks(inp)
        assert ValidationBlockReason.DIGEST_MISMATCH.value in blocks
        assert ValidationBlockReason.APPROVAL_DIGEST_MISMATCH.value in blocks
        assert open_ids  # treated as open due to mismatch

    def test_missing_original_files_blocks(self) -> None:
        inp = _confirmed_input(original_files=())
        manifest = validate_filing_package(
            inp, id_factory=_id_factory, package_id="pkg:empty"
        )
        assert ValidationBlockReason.MISSING_ORIGINAL_FILES.value in (
            manifest.block_reasons
        )
        assert ValidationBlockReason.EMPTY_PACKAGE.value in manifest.block_reasons

    def test_missing_checklist_categories_blocks(self) -> None:
        # Only one mandatory category present (forms) — others missing.
        partial_open = (
            OperatorChecklistItem(
                item_id="check:only-forms",
                category=ChecklistCategory.FORMS,
                summary="forms only",
            ),
        )
        inp = _ready_input(operator_checklist=partial_open)
        # Confirm whatever is present
        confirmed = confirm_checklist_items(
            inp,
            confirmed_by="Pat Attorney",
            confirmed_at_utc="2026-03-15T14:00:00Z",
        )
        manifest = validate_filing_package(
            confirmed, id_factory=_id_factory, package_id="pkg:partial-check"
        )
        assert ValidationBlockReason.MISSING_CHECKLIST_CATEGORIES.value in (
            manifest.block_reasons
        )

    def test_quarantine_blocks(self) -> None:
        inp = _confirmed_input(classification=DisclosureClassification.UNKNOWN)
        manifest = validate_filing_package(
            inp, id_factory=_id_factory, package_id="pkg:quarantine"
        )
        assert ValidationBlockReason.QUARANTINE_BLOCK.value in (
            manifest.block_reasons
        )

    def test_validate_raise_if_blocked(self) -> None:
        with pytest.raises(PackageValidationBlockedError):
            validate_filing_package(
                _ready_input(),
                id_factory=_id_factory,
                raise_if_blocked=True,
            )

    def test_validated_happy_path(self) -> None:
        _reset()
        inp = _confirmed_input()
        manifest = validate_filing_package(
            inp, id_factory=_id_factory, package_id="pkg:ok"
        )
        assert manifest.state is FilingPackageState.VALIDATED
        assert manifest.is_validated
        assert not manifest.block_reasons
        assert not manifest.open_confirmation_ids
        assert manifest.review_state is ReviewState.COMPLETE
        assert FilingPackageReasonCode.PACKAGE_VALIDATED.value in (
            manifest.reason_codes
        )
        assert package_inputs_match(manifest, inp)
        assert FILING_PACKAGE_SCHEMA_VERSION == manifest.schema_version
        assert manifest.output_kind == OUTPUT_KIND_FILING_PACKAGE
        assert FILING_PACKAGE_DISCLAIMER in manifest.disclaimer or (
            manifest.disclaimer == FILING_PACKAGE_DISCLAIMER
        )


# ---------------------------------------------------------------------------
# Material digest stability and invalidation
# ---------------------------------------------------------------------------


class TestMaterialDigestAndInvalidation:
    def test_package_digest_stable_for_same_inputs(self) -> None:
        a = _ready_input()
        b = _ready_input()
        assert a.package_digest() == b.package_digest()

    def test_confirmation_does_not_change_material_digest(self) -> None:
        raw = _ready_input()
        confirmed = confirm_checklist_items(
            raw,
            confirmed_by="Pat Attorney",
            confirmed_at_utc="2026-03-15T14:00:00Z",
        )
        assert raw.package_digest() == confirmed.package_digest()
        # Confirmations bind to that digest
        for item in confirmed.operator_checklist:
            if item.confirmed:
                assert item.bound_package_digest == raw.package_digest()

    def test_material_change_changes_digest(self) -> None:
        a = _ready_input()
        files = list(_original_files())
        # Mutate DOCX digest
        files[0] = PackageFileEntry(
            file_id="file:spec-docx",
            family=PackageArtifactFamily.ORIGINAL_FILE,
            role=OriginalFileRole.SPECIFICATION,
            media_kind=MediaKind.DOCX,
            content_digest=sha256_hex(b"mutated-spec-docx"),
            filename="specification.docx",
            source_root="vault://tenant-a/matters/m1/originals",
        )
        b = _ready_input(original_files=tuple(files))
        assert a.package_digest() != b.package_digest()

    def test_material_change_invalidates_approval(self) -> None:
        c = _compiler()
        inp = _confirmed_input()
        validated = c.validate(inp, package_id="pkg:inv-1")
        assert validated.is_validated
        approved, approval = c.bind_approval(
            validated,
            approver_name="Pat Attorney",
            approved_at_utc="2026-03-15T15:00:00Z",
            statement="I approve this exact package digest for external handoff.",
            package_input=inp,
        )
        assert approval.binds_package_digest(validated.package_digest)
        assert approved.approval is not None

        # Mutate ADS field → new material digest
        ads = list(_ads_fields())
        ads[0] = ProposedAdsField(
            field_id="ads:title",
            field_name="invention_title",
            proposed_value="Temperature Sensing Apparatus (REVISED)",
        )
        mutated = _confirmed_input(proposed_ads_fields=tuple(ads))
        assert not package_inputs_match(approved, mutated)

        invalidated = c.revalidate_against_inputs(approved, mutated)
        assert invalidated.state is FilingPackageState.INVALIDATED
        assert invalidated.approval is None
        assert ValidationBlockReason.MATERIAL_INPUTS_CHANGED.value in (
            invalidated.block_reasons
        )
        assert FilingPackageReasonCode.APPROVAL_INVALIDATED.value in (
            invalidated.reason_codes
        )

    def test_bind_approval_rejects_digest_drift(self) -> None:
        c = _compiler()
        inp = _confirmed_input()
        validated = c.validate(inp, package_id="pkg:inv-2")
        ads = list(_ads_fields())
        ads[0] = ProposedAdsField(
            field_id="ads:title",
            field_name="invention_title",
            proposed_value="Changed Title",
        )
        mutated = _confirmed_input(proposed_ads_fields=tuple(ads))
        with pytest.raises(PackageApprovalInvalidatedError):
            c.bind_approval(
                validated,
                approver_name="Pat Attorney",
                approved_at_utc="2026-03-15T15:00:00Z",
                statement="should fail",
                package_input=mutated,
            )

    def test_bind_approval_requires_validated(self) -> None:
        c = _compiler()
        draft = c.compile(_ready_input(), package_id="pkg:draft-only")
        with pytest.raises(PackageNotValidatedError):
            c.bind_approval(
                draft,
                approver_name="Pat Attorney",
                approved_at_utc="2026-03-15T15:00:00Z",
                statement="nope",
            )

    def test_revalidate_same_inputs_keeps_validated(self) -> None:
        c = _compiler()
        inp = _confirmed_input()
        validated = c.validate(inp, package_id="pkg:stable")
        again = c.revalidate_against_inputs(validated, inp)
        assert again.state is FilingPackageState.VALIDATED
        assert again.package_digest == validated.package_digest


# ---------------------------------------------------------------------------
# Round-trip / public projection
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_round_trip_manifest(self) -> None:
        _reset()
        manifest = validate_filing_package(
            _confirmed_input(), id_factory=_id_factory, package_id="pkg:rt"
        )
        revived = FilingPackageManifest.from_dict(manifest.to_dict())
        assert revived.to_dict() == manifest.to_dict()
        assert revived.content_digest == manifest.content_digest
        assert canonical_json(revived.to_dict()) == canonical_json(manifest.to_dict())

    def test_round_trip_input(self) -> None:
        inp = _confirmed_input()
        revived = FilingPackageInput.from_dict(inp.to_dict())
        assert revived.package_digest() == inp.package_digest()

    def test_public_projection_has_no_capabilities(self) -> None:
        manifest = validate_filing_package(
            _confirmed_input(), id_factory=_id_factory, package_id="pkg:pub"
        )
        pub = manifest.public_projection()
        assert pub["is_submitted"] is False
        assert pub["can_sign"] is False
        assert pub["filing_is_external"] is True
        assert pub["certification_asserted"] is False
        # No ADS proposed values in public projection
        assert "proposed_metadata" not in pub
        assert "original_files" not in pub


# ---------------------------------------------------------------------------
# Golden fixture
# ---------------------------------------------------------------------------


class TestGoldenManifest:
    def test_golden_manifest_exists_and_matches_compiler(self) -> None:
        assert _GOLDEN_PATH.is_file(), f"missing golden fixture: {_GOLDEN_PATH}"
        golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
        assert golden["schema_version"] == FILING_PACKAGE_SCHEMA_VERSION
        assert golden["fixture_id"] == "patlaw-153-filing-package-golden"
        assert golden["task_id"] == "PATLAW-153"

        # Rebuild from golden recipe (material inputs)
        recipe = golden["input_recipe"]
        files = tuple(PackageFileEntry.from_dict(f) for f in recipe["original_files"])
        ads = tuple(ProposedAdsField.from_dict(a) for a in recipe["proposed_ads_fields"])
        drawings = tuple(
            DrawingsInventoryItem.from_dict(d) for d in recipe["drawings_inventory"]
        )
        checklist = tuple(
            OperatorChecklistItem.from_dict(c) for c in recipe["operator_checklist"]
        )
        inp = FilingPackageInput(
            matter_id=recipe["matter_id"],
            application_type=recipe["application_type"],
            original_files=files,
            proposed_ads_fields=ads,
            drawings_inventory=drawings,
            operator_checklist=checklist,
            rule_pack=RulePackBinding.from_dict(recipe["rule_pack"]),
            prior_art=PriorArtCoverageBinding.from_dict(recipe["prior_art"]),
            classification=recipe["classification"],
            portfolio_fact_digest=recipe.get("portfolio_fact_digest"),
            candidate_dates_digest=recipe.get("candidate_dates_digest"),
            source_roots=tuple(recipe.get("source_roots") or ()),
            warnings=tuple(recipe.get("warnings") or ()),
            labels=recipe.get("labels") or {},
        )
        confirmed = confirm_checklist_items(
            inp,
            confirmed_by=recipe["confirm"]["confirmed_by"],
            confirmed_at_utc=recipe["confirm"]["confirmed_at_utc"],
        )
        _reset()
        manifest = validate_filing_package(
            confirmed,
            id_factory=_id_factory,
            package_id=golden["expected"]["package_id"],
        )
        assert manifest.state is FilingPackageState.VALIDATED
        assert manifest.package_digest == golden["expected"]["package_digest"]
        assert manifest.content_digest == golden["expected"]["content_digest"]

        # Families present in golden expected snapshot
        exp = golden["expected"]
        assert "proposed_metadata" in exp
        assert "original_files" in exp
        assert "rendered_derivatives" in exp
        assert "operator_checklist" in exp
        assert exp["state"] == "validated"
        assert not exp["block_reasons"]
        assert set(exp["mandatory_checklist_categories_present"]) == set(
            MANDATORY_CHECKLIST_CATEGORIES
        )

        # Round-trip expected manifest fragment
        assert len(manifest.original_files) == len(exp["original_files"])
        assert len(manifest.rendered_derivatives) == len(exp["rendered_derivatives"])
        assert {
            f.file_id for f in manifest.original_files
        } == {f["file_id"] for f in exp["original_files"]}
        assert {
            f.file_id for f in manifest.rendered_derivatives
        } == {f["file_id"] for f in exp["rendered_derivatives"]}


# ---------------------------------------------------------------------------
# Helpers / evaluate API
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_default_mandatory_checklist_covers_categories(self) -> None:
        items = default_mandatory_checklist()
        cats = {
            i.category.value
            if isinstance(i.category, ChecklistCategory)
            else str(i.category)
            for i in items
        }
        assert cats == set(MANDATORY_CHECKLIST_CATEGORIES)

    def test_module_level_compile(self) -> None:
        m = compile_filing_package(
            _ready_input(), id_factory=_id_factory, package_id="pkg:mod"
        )
        assert m.state is FilingPackageState.DRAFT
        assert FilingPackageReasonCode.PACKAGE_COMPILED.value in m.reason_codes
