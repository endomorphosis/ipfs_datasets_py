"""Unit tests for Federal Register discovery and GovInfo verification (PATLAW-014).

Acceptance:

* Unofficial API text never masquerades as official edition.
* Proposed and withdrawn rules remain nonbinding.
* Effective/compliance dates and corrections survive replay.
* Retry/schema/signature failures are explicit.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.patent_authority_sources import (
    AuthorityTier,
    HardCodedLatestEditionError,
    IdentityRole,
    VerificationState,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.govinfo_client import (
    FIXTURE_SCHEMA_VERSION as GOVINFO_FIXTURE_SCHEMA,
    SCHEMA_VERSION as GOVINFO_SCHEMA,
    GovInfoClient,
    GovInfoRetryError,
    GovInfoSchemaError,
    GovInfoSignatureError,
    GranuleFormat,
    PackageNotFoundError,
    ResolutionStatus as GovInfoResolutionStatus,
    SignatureEvidence,
    SignatureResult,
    content_sha256 as govinfo_sha256,
    govinfo_granule_pdf_url,
    govinfo_package_url,
    normalize_package_id,
    signature_result_to_verification_state,
)
from ipfs_datasets_py.processors.legal_scrapers.federal_scrapers.federal_register_change_processor import (
    FIXTURE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    BindingElevationError,
    ChangeRelation,
    DiscoveryDocument,
    DocumentNotFoundError,
    FederalRegisterChangeProcessor,
    ResolutionStatus,
    RetryFailureError,
    RuleChangeRecord,
    RuleDocumentType,
    SchemaFailureError,
    SignatureFailureError,
    UnofficialMasqueradeError,
    assert_not_masquerading_as_official,
    build_patent_rule_changes_fixture_recipe,
    content_sha256,
    default_fixture_dir,
    is_binding_document_type,
    normalize_document_number,
    stable_rule_identity,
    write_default_fixtures,
)

# tests/unit/processors/legal_scrapers/federal_scrapers/this_file.py
# parents[4] == tests/
_REPO_FIXTURE_DIR = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "legal_data"
    / "patent_authorities"
    / "federal_register"
)


def _fixture_dir() -> Path:
    candidate = default_fixture_dir()
    if (candidate / "patent_rule_changes_recipe.json").is_file():
        return candidate
    if (_REPO_FIXTURE_DIR / "patent_rule_changes_recipe.json").is_file():
        return _REPO_FIXTURE_DIR
    write_default_fixtures(_REPO_FIXTURE_DIR)
    return _REPO_FIXTURE_DIR


@pytest.fixture(scope="module")
def fixture_dir() -> Path:
    return _fixture_dir()


@pytest.fixture
def processor(fixture_dir: Path) -> FederalRegisterChangeProcessor:
    return FederalRegisterChangeProcessor(fixture_dir=fixture_dir)


@pytest.fixture
def govinfo(fixture_dir: Path) -> GovInfoClient:
    client = GovInfoClient(fixture_dir=fixture_dir)
    client.acquire_from_fixture()
    return client


@pytest.fixture
def acquisition(processor: FederalRegisterChangeProcessor):
    return processor.acquire_from_fixture()


# ---------------------------------------------------------------------------
# Unofficial API text never masquerades as official edition
# ---------------------------------------------------------------------------


def test_discovery_is_unofficial_current(acquisition):
    assert acquisition.records
    for record in acquisition.records.values():
        if record.discovery is None:
            continue
        disc = record.discovery
        assert disc.authority_tier is AuthorityTier.UNOFFICIAL_CURRENT
        assert disc.authority_tier.value == "unofficial-current"
        assert disc.is_official_edition is False
        assert disc.is_binding is False
        payload = disc.to_dict()
        assert payload["authority_tier"] == "unofficial-current"
        assert payload["is_official_edition"] is False
        assert payload["is_binding"] is False


def test_unofficial_never_masquerades_as_official(acquisition):
    assert acquisition.every_unofficial_is_not_official()
    for record in acquisition.records.values():
        if record.derived_presentation is not None:
            assert record.derived_presentation.role is IdentityRole.DERIVED_PRESENTATION
            assert "federalregister.gov" in record.derived_presentation.provider or (
                record.derived_presentation.provider
                in ("federalregister.gov", "federalregister", "fr_api")
            )
        if record.official_artifact is not None:
            assert record.official_artifact.role is IdentityRole.OFFICIAL_ARTIFACT
            assert "federalregister.gov" not in record.official_artifact.provider.lower()
            assert record.official_artifact.provider == "govinfo"
            assert record.authority_tier is AuthorityTier.OFFICIAL_CHANGE


def test_assert_not_masquerading_rejects_fr_gov_as_official():
    with pytest.raises(UnofficialMasqueradeError):
        assert_not_masquerading_as_official(
            authority_tier=AuthorityTier.OFFICIAL_CHANGE,
            provider="federalregister.gov",
            is_official_edition=True,
        )
    with pytest.raises(UnofficialMasqueradeError):
        assert_not_masquerading_as_official(
            authority_tier=AuthorityTier.UNOFFICIAL_CURRENT,
            identity_role=IdentityRole.OFFICIAL_ARTIFACT,
            provider="federalregister.gov",
        )
    # GovInfo official path is allowed.
    assert_not_masquerading_as_official(
        authority_tier=AuthorityTier.OFFICIAL_CHANGE,
        identity_role=IdentityRole.OFFICIAL_ARTIFACT,
        provider="govinfo",
        is_official_edition=True,
    )


def test_discovery_document_rejects_hard_coded_latest():
    with pytest.raises(HardCodedLatestEditionError):
        DiscoveryDocument(
            document_number="latest",
            document_type=RuleDocumentType.PROPOSED_RULE,
            title="Bad",
        )


def test_official_and_derived_identities_remain_distinct(acquisition):
    final = acquisition.get_record("2024-05512")
    assert final.official_artifact is not None
    assert final.derived_presentation is not None
    assert final.official_artifact.artifact_sha256 != final.derived_presentation.artifact_sha256
    assert final.official_artifact.role is IdentityRole.OFFICIAL_ARTIFACT
    assert final.derived_presentation.role is IdentityRole.DERIVED_PRESENTATION
    assert final.official_artifact.provider == "govinfo"
    assert "federalregister.gov" in final.derived_presentation.provider


def test_authority_registry_labels_tiers(
    processor: FederalRegisterChangeProcessor, acquisition
):
    for key, source in acquisition.authority_sources.items():
        assert key in processor.registry
        stored = processor.registry.get(key)
        assert stored.authority_tier in (
            AuthorityTier.OFFICIAL_CHANGE,
            AuthorityTier.UNOFFICIAL_CURRENT,
        )
        if stored.official_artifact is not None:
            assert stored.authority_tier is AuthorityTier.OFFICIAL_CHANGE
            assert stored.official_artifact.provider == "govinfo"
        else:
            assert stored.authority_tier is AuthorityTier.UNOFFICIAL_CURRENT


# ---------------------------------------------------------------------------
# Proposed and withdrawn rules remain nonbinding
# ---------------------------------------------------------------------------


def test_proposed_rules_are_nonbinding(acquisition):
    proposed = acquisition.proposed_rules()
    assert proposed
    assert any(r.document_number == "2023-10001" for r in proposed)
    for record in proposed:
        assert record.is_binding is False
        assert record.document_type is RuleDocumentType.PROPOSED_RULE
        assert not is_binding_document_type(record.document_type) or record.is_binding is False
        assert is_binding_document_type(RuleDocumentType.PROPOSED_RULE) is False
        payload = record.to_dict()
        assert payload["is_binding"] is False


def test_withdrawn_rules_are_nonbinding(acquisition):
    withdrawn = acquisition.withdrawn_rules()
    assert withdrawn
    docs = {r.document_number for r in withdrawn}
    assert "2023-10002" in docs or "2024-07001" in docs
    for record in withdrawn:
        assert record.is_binding is False
        assert record.withdrawn is True or record.document_type is RuleDocumentType.WITHDRAWAL


def test_every_proposed_and_withdrawn_nonbinding(acquisition):
    assert acquisition.every_proposed_and_withdrawn_nonbinding()


def test_binding_elevation_rejected_for_proposed():
    with pytest.raises(BindingElevationError):
        RuleChangeRecord(
            document_number="2023-10001",
            document_type=RuleDocumentType.PROPOSED_RULE,
            title="Proposed",
            is_binding=True,
        )


def test_binding_elevation_rejected_for_withdrawal():
    with pytest.raises(BindingElevationError):
        RuleChangeRecord(
            document_number="2024-07001",
            document_type=RuleDocumentType.WITHDRAWAL,
            title="Withdrawal",
            is_binding=True,
            withdrawn=True,
        )


def test_final_rule_may_be_binding_when_official(acquisition):
    final = acquisition.get_record("2024-05512")
    assert final.document_type is RuleDocumentType.FINAL_RULE
    assert final.is_binding is True
    assert final.official_artifact is not None
    assert final.authority_tier is AuthorityTier.OFFICIAL_CHANGE


def test_interim_final_may_be_binding(acquisition):
    interim = acquisition.get_record("2024-09001")
    assert interim.document_type is RuleDocumentType.INTERIM_FINAL_RULE
    assert interim.is_binding is True
    assert interim.official_artifact is not None


def test_is_binding_document_type_matrix():
    assert is_binding_document_type("proposed_rule") is False
    assert is_binding_document_type("withdrawal") is False
    assert is_binding_document_type("notice") is False
    assert is_binding_document_type("final_rule") is True
    assert is_binding_document_type("interim_final_rule") is True
    assert is_binding_document_type("correction") is True


# ---------------------------------------------------------------------------
# Effective/compliance dates and corrections survive replay
# ---------------------------------------------------------------------------


def test_effective_and_compliance_dates_present(acquisition):
    final = acquisition.get_record("2024-05512")
    assert final.effective_date == date(2024, 5, 1)
    assert final.compliance_date == date(2024, 6, 1)
    payload = final.to_dict()
    assert payload["effective_date"] == "2024-05-01"
    assert payload["compliance_date"] == "2024-06-01"

    interim = acquisition.get_record("2024-09001")
    assert interim.effective_date == date(2024, 4, 20)
    assert interim.compliance_date == date(2024, 5, 20)


def test_correction_links_survive(acquisition):
    correction = acquisition.get_record("2024-06001")
    assert correction.document_type is RuleDocumentType.CORRECTION
    assert correction.corrects == "2024-05512"
    assert correction.effective_date == date(2024, 5, 1)
    corrections = acquisition.corrections()
    assert any(c.document_number == "2024-06001" for c in corrections)
    # Edge present.
    edge_pairs = {
        (e.relation, e.source_document_number, e.target_document_number)
        for e in acquisition.edges
    }
    assert (
        ChangeRelation.CORRECTS,
        "2024-06001",
        "2024-05512",
    ) in edge_pairs


def test_withdrawal_and_delay_edges_survive(acquisition):
    withdrawal = acquisition.get_record("2024-07001")
    assert withdrawal.withdraws == "2023-10002"
    delay = acquisition.get_record("2024-08001")
    assert delay.delays == "2024-05512"
    assert delay.delayed_effective_date == date(2024, 7, 1)
    assert delay.document_type is RuleDocumentType.DELAY_EFFECTIVE_DATE

    relations = {
        (e.relation, e.source_document_number, e.target_document_number)
        for e in acquisition.edges
    }
    assert (ChangeRelation.WITHDRAWS, "2024-07001", "2023-10002") in relations
    assert (
        ChangeRelation.DELAYS_EFFECTIVE_DATE,
        "2024-08001",
        "2024-05512",
    ) in relations


def test_replay_preserves_temporal_fields(
    processor: FederalRegisterChangeProcessor, fixture_dir: Path
):
    assert processor.replay_preserves_temporal_fields(
        fixture_dir / "patent_rule_changes_recipe.json"
    )
    a = processor.acquire_from_fixture(register=False)
    b = processor.acquire_from_fixture(register=False)
    assert a.to_canonical_json() == b.to_canonical_json()
    # Spot-check temporal fields equal across replay.
    for doc in ("2024-05512", "2024-06001", "2024-08001", "2024-09001"):
        ra, rb = a.get_record(doc), b.get_record(doc)
        assert ra.effective_date == rb.effective_date
        assert ra.compliance_date == rb.compliance_date
        assert ra.delayed_effective_date == rb.delayed_effective_date
        assert ra.corrects == rb.corrects
        assert ra.withdraws == rb.withdraws
        assert ra.delays == rb.delays


def test_records_with_temporal_fields(acquisition):
    temporal = acquisition.records_with_temporal_fields()
    docs = {r.document_number for r in temporal}
    assert "2024-05512" in docs
    assert "2024-09001" in docs
    assert "2024-08001" in docs


def test_canonical_json_stable(acquisition):
    blob1 = acquisition.to_canonical_json()
    blob2 = acquisition.to_canonical_json()
    assert blob1 == blob2
    payload = json.loads(blob1)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert "2024-05512" in payload["records"]
    assert payload["records"]["2024-05512"]["effective_date"] == "2024-05-01"
    assert payload["records"]["2024-05512"]["compliance_date"] == "2024-06-01"
    assert payload["records"]["2024-06001"]["corrects"] == "2024-05512"


# ---------------------------------------------------------------------------
# Retry / schema / signature failures are explicit
# ---------------------------------------------------------------------------


def test_retry_failure_is_explicit(govinfo: GovInfoClient):
    result = govinfo.record_retry_failure(
        package_id="FR-2099-01-01",
        attempts=5,
        last_status=429,
        retry_after=120.0,
    )
    assert result.status is GovInfoResolutionStatus.RETRY_FAILED
    assert result.is_failure is True
    assert result.failure is not None
    assert result.failure["kind"] == "retry"
    assert result.failure["error_code"] == "retry_exhausted"
    assert result.failure["attempts"] == 5
    assert result.failure["last_status"] == 429
    assert result.verification_state is VerificationState.UNVERIFIED


def test_schema_failure_is_explicit(govinfo: GovInfoClient):
    result = govinfo.record_schema_failure(
        message="package payload missing required package_id field",
        package_id="FR-BAD-PACKAGE",
        field_name="package_id",
    )
    assert result.status is GovInfoResolutionStatus.SCHEMA_FAILED
    assert result.is_failure is True
    assert result.failure is not None
    assert result.failure["kind"] == "schema"
    assert result.failure["field_name"] == "package_id"


def test_signature_failure_is_explicit(govinfo: GovInfoClient):
    result = govinfo.record_signature_failure(
        package_id="FR-2024-03-15",
        granule_id="2024-99999",
        signature_result=SignatureResult.INVALID,
    )
    assert result.status is GovInfoResolutionStatus.SIGNATURE_FAILED
    assert result.is_failure is True
    assert result.failure is not None
    assert result.failure["kind"] == "signature"
    assert result.failure["signature_result"] == "invalid"
    assert result.signature is not None
    assert result.signature.result is SignatureResult.INVALID


def test_verify_granule_or_raise_typed_errors(govinfo: GovInfoClient):
    govinfo._failure_fixtures["retry:FR-RETRY-1"] = {
        "kind": "retry",
        "package_id": "FR-RETRY-1",
        "attempts": 3,
        "last_status": 503,
        "message": "retry exhausted",
    }
    with pytest.raises(GovInfoRetryError) as retry_exc:
        govinfo.verify_granule_or_raise(package_id="FR-RETRY-1", granule_id="g1")
    assert retry_exc.value.attempts == 3
    assert retry_exc.value.error_code == "retry_exhausted"

    govinfo._failure_fixtures["schema:FR-SCHEMA-1"] = {
        "kind": "schema",
        "package_id": "FR-SCHEMA-1",
        "field_name": "granules",
        "message": "schema invalid",
    }
    with pytest.raises(GovInfoSchemaError) as schema_exc:
        govinfo.verify_granule_or_raise(package_id="FR-SCHEMA-1", granule_id="g1")
    assert schema_exc.value.field_name == "granules" or schema_exc.value.error_code

    govinfo._failure_fixtures["signature:FR-2024-03-15:bad-granule"] = {
        "kind": "signature",
        "package_id": "FR-2024-03-15",
        "granule_id": "bad-granule",
        "signature_result": "invalid",
        "message": "bad signature",
    }
    with pytest.raises(GovInfoSignatureError) as sig_exc:
        govinfo.verify_granule_or_raise(
            package_id="FR-2024-03-15", granule_id="bad-granule"
        )
    assert sig_exc.value.signature_result is SignatureResult.INVALID
    assert sig_exc.value.granule_id == "bad-granule"


def test_processor_raises_typed_explicit_failures(
    processor: FederalRegisterChangeProcessor,
):
    retry = processor.explicit_retry_failure(
        package_id="FR-2099-01-01", attempts=5, last_status=429
    )
    with pytest.raises(RetryFailureError) as ei:
        processor.raise_for_verification_failure(retry)
    assert ei.value.failure["kind"] == "retry"

    schema = processor.explicit_schema_failure(
        message="bad schema", package_id="FR-BAD", field_name="package_id"
    )
    with pytest.raises(SchemaFailureError):
        processor.raise_for_verification_failure(schema)

    sig = processor.explicit_signature_failure(
        package_id="FR-2024-03-15",
        granule_id="2024-99999",
        signature_result="invalid",
    )
    with pytest.raises(SignatureFailureError):
        processor.raise_for_verification_failure(sig)


def test_fixture_failure_recipes_load(govinfo: GovInfoClient):
    # Failure fixtures from recipe should be registered.
    assert any(
        "retry" in k or (isinstance(v, dict) and v.get("kind") == "retry")
        for k, v in govinfo._failure_fixtures.items()
    )
    result = govinfo.verify_granule(
        package_id="FR-2099-01-01", granule_id="anything"
    )
    assert result.status is GovInfoResolutionStatus.RETRY_FAILED
    assert result.failure is not None
    assert result.failure["kind"] == "retry"


def test_successful_govinfo_verification(govinfo: GovInfoClient):
    result = govinfo.verify_granule(
        package_id="FR-2024-03-15",
        granule_id="2024-05512",
        require_valid_signature=True,
    )
    assert result.status is GovInfoResolutionStatus.VERIFIED
    assert result.is_verified is True
    assert result.official_artifact is not None
    assert result.official_artifact.role is IdentityRole.OFFICIAL_ARTIFACT
    assert result.signature is not None
    assert result.signature.result is SignatureResult.VALID
    assert result.verification_state is VerificationState.VERIFIED
    assert result.package_id == "FR-2024-03-15"
    assert result.granule_id == "2024-05512"
    assert "pdf" in (result.granule.formats if result.granule else {})


def test_govinfo_package_and_granule_metadata(govinfo: GovInfoClient):
    pkg = govinfo.get_package("FR-2024-03-15")
    assert pkg.package_id == "FR-2024-03-15"
    assert pkg.collection == "FR"
    assert pkg.content_sha256 is not None
    gran = pkg.get_granule("2024-05512")
    assert gran.document_number == "2024-05512"
    assert GranuleFormat.PDF.value in gran.formats
    assert GranuleFormat.XML.value in gran.formats
    assert gran.formats["pdf"].artifact_sha256 != gran.formats["xml"].artifact_sha256
    with pytest.raises(PackageNotFoundError):
        govinfo.get_package("FR-1900-01-01")


# ---------------------------------------------------------------------------
# Identity helpers, missing discovery, fixtures
# ---------------------------------------------------------------------------


def test_stable_rule_identity():
    assert stable_rule_identity(document_number="2024-05512") == "fr:us:2024-05512"
    assert normalize_document_number("2024-05512") == "2024-05512"
    with pytest.raises(HardCodedLatestEditionError):
        normalize_document_number("latest")


def test_normalize_package_id():
    assert normalize_package_id("FR-2024-03-15") == "FR-2024-03-15"
    assert normalize_package_id("2024-03-15") == "FR-2024-03-15"
    with pytest.raises(HardCodedLatestEditionError):
        normalize_package_id("latest")
    url = govinfo_package_url("FR-2024-03-15")
    assert url.endswith("/FR-2024-03-15")
    pdf = govinfo_granule_pdf_url(package_id="FR-2024-03-15", granule_id="2024-05512")
    assert "2024-05512.pdf" in pdf


def test_signature_result_mapping():
    assert (
        signature_result_to_verification_state(SignatureResult.VALID)
        is VerificationState.VERIFIED
    )
    assert (
        signature_result_to_verification_state(SignatureResult.INVALID)
        is VerificationState.CONFLICT
    )
    assert (
        signature_result_to_verification_state(SignatureResult.MISSING)
        is VerificationState.INCONCLUSIVE
    )
    evidence = SignatureEvidence(result="valid", algorithm="GPO-PAdES")
    assert evidence.is_valid is True
    assert evidence.to_dict()["result"] == "valid"


def test_missing_discovery_yields_unknown(
    processor: FederalRegisterChangeProcessor, fixture_dir: Path
):
    acq = processor.acquire_from_fixture(
        fixture_dir / "patent_rule_missing_discovery.json"
    )
    assert acq.status is ResolutionStatus.UNKNOWN
    assert acq.is_unknown
    assert acq.unknown_reason
    assert not acq.records


def test_acquire_unknown_helper(processor: FederalRegisterChangeProcessor):
    acq = processor.acquire_unknown(reason="operator withheld discovery")
    assert acq.status is ResolutionStatus.UNKNOWN
    assert acq.unknown_reason == "operator withheld discovery"


def test_document_not_found(acquisition):
    with pytest.raises(DocumentNotFoundError):
        acquisition.get_record("9999-00000")


def test_fixture_recipe_schema_and_contents(fixture_dir: Path):
    recipe_path = fixture_dir / "patent_rule_changes_recipe.json"
    assert recipe_path.is_file()
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    assert recipe["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert recipe["discovery"]
    assert recipe["records"]
    assert recipe["govinfo_packages"]
    assert recipe["govinfo_failures"]
    doc_nums = {r["document_number"] for r in recipe["records"]}
    assert "2024-05512" in doc_nums
    assert "2023-10001" in doc_nums
    assert "2024-06001" in doc_nums


def test_build_recipe_matches_on_disk(fixture_dir: Path):
    generated = build_patent_rule_changes_fixture_recipe()
    on_disk = json.loads(
        (fixture_dir / "patent_rule_changes_recipe.json").read_text(encoding="utf-8")
    )
    assert generated["fixture_id"] == on_disk["fixture_id"]
    gen_docs = {r["document_number"] for r in generated["records"]}
    disk_docs = {r["document_number"] for r in on_disk["records"]}
    assert gen_docs == disk_docs
    assert len(generated["edges"]) == len(on_disk["edges"])
    assert len(generated["govinfo_failures"]) == len(on_disk["govinfo_failures"])


def test_content_sha256_deterministic():
    assert content_sha256("abc") == content_sha256(b"abc")
    assert content_sha256("abc") == govinfo_sha256("abc")
    assert content_sha256("abc") != content_sha256("abd")


def test_all_document_kinds_represented(acquisition):
    kinds = {r.document_type for r in acquisition.records.values()}
    assert RuleDocumentType.PROPOSED_RULE in kinds
    assert RuleDocumentType.FINAL_RULE in kinds
    assert RuleDocumentType.CORRECTION in kinds
    assert RuleDocumentType.WITHDRAWAL in kinds
    assert RuleDocumentType.DELAY_EFFECTIVE_DATE in kinds
    assert RuleDocumentType.INTERIM_FINAL_RULE in kinds


def test_list_document_numbers(processor: FederalRegisterChangeProcessor, acquisition):
    nums = processor.list_document_numbers(acquisition)
    assert "2024-05512" in nums
    assert nums == sorted(nums)


def test_govinfo_schema_constants():
    assert GOVINFO_SCHEMA.startswith("govinfo")
    assert GOVINFO_FIXTURE_SCHEMA.startswith("govinfo")
    assert SCHEMA_VERSION.startswith("federal-register")
    assert FIXTURE_SCHEMA_VERSION.startswith("federal-register")
