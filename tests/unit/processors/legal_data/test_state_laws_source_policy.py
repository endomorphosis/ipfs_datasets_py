"""Unit tests for the state-law official-source catalog and admission policy (LCR-002).

Acceptance: catalog contains exactly 51 unique postal codes including DC, at
least one authoritative acquisition path per code, and rejects
mutable/secondary-only admission.
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    AUTHORITATIVE_ROLES,
    CANONICAL_JURISDICTIONS,
    CANONICAL_JURISDICTION_NAMES,
    CATALOG_SCHEMA_VERSION,
    EXPECTED_JURISDICTION_COUNT,
    SCHEMA_VERSION,
    TASK_ID,
    AcquisitionPath,
    AdmissionRequest,
    AuthorityClass,
    CatalogSchemaError,
    DomainConstraintError,
    JurisdictionSetError,
    MissingAuthoritativePathError,
    MutableReferenceError,
    OfficialSourceCatalog,
    SecondaryOnlyAdmissionError,
    SourceRole,
    assert_catalog_invariants,
    catalog_authoritative_coverage,
    clear_catalog_cache,
    default_catalog_path,
    evaluate_admission,
    get_official_source_catalog,
    is_mutable_reference,
    is_secondary_host,
    load_official_source_catalog,
    normalize_postal_code,
    reject_mutable_reference,
    require_authoritative_admission,
    validate_jurisdiction_set,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_catalog_cache()
    yield
    clear_catalog_cache()


@pytest.fixture(scope="module")
def sealed_catalog() -> OfficialSourceCatalog:
    return load_official_source_catalog()


def _catalog_payload() -> dict:
    path = default_catalog_path()
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Schema / sealed set
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "state-laws-source-policy-v1"
    assert CATALOG_SCHEMA_VERSION == "state-laws-official-source-catalog-v1"
    assert TASK_ID == "LCR-002"
    assert EXPECTED_JURISDICTION_COUNT == 51


def test_canonical_jurisdiction_set_is_exact_51_including_dc() -> None:
    assert len(CANONICAL_JURISDICTIONS) == 51
    assert "DC" in CANONICAL_JURISDICTIONS
    assert "PR" not in CANONICAL_JURISDICTIONS
    assert set(CANONICAL_JURISDICTION_NAMES) == CANONICAL_JURISDICTIONS
    validate_jurisdiction_set(sorted(CANONICAL_JURISDICTIONS))


def test_validate_jurisdiction_set_rejects_missing_extra_and_duplicates() -> None:
    codes = sorted(CANONICAL_JURISDICTIONS)
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(codes[:-1])
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(codes + ["PR"])
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(codes + ["AL"])


def test_normalize_postal_code_rejects_unknown() -> None:
    assert normalize_postal_code("or") == "OR"
    with pytest.raises(JurisdictionSetError):
        normalize_postal_code("XX")
    with pytest.raises(JurisdictionSetError):
        normalize_postal_code("USA")


# ---------------------------------------------------------------------------
# Catalog: 51 codes, DC, authoritative path per code
# ---------------------------------------------------------------------------


def test_default_catalog_path_exists() -> None:
    path = default_catalog_path()
    assert path.is_file()
    assert path.as_posix().endswith("data/legal/state_laws/official_source_catalog.json")


def test_sealed_catalog_has_exactly_51_unique_postal_codes_including_dc(
    sealed_catalog: OfficialSourceCatalog,
) -> None:
    codes = sealed_catalog.postal_codes()
    assert len(codes) == 51
    assert len(set(codes)) == 51
    assert "DC" in codes
    assert set(codes) == CANONICAL_JURISDICTIONS
    assert sealed_catalog.jurisdiction_count == 51
    assert sealed_catalog.schema_version == CATALOG_SCHEMA_VERSION
    assert sealed_catalog.task_id == TASK_ID


def test_each_jurisdiction_has_at_least_one_authoritative_path(
    sealed_catalog: OfficialSourceCatalog,
) -> None:
    coverage = catalog_authoritative_coverage(sealed_catalog)
    assert set(coverage) == CANONICAL_JURISDICTIONS
    for code, path_ids in coverage.items():
        assert path_ids, f"{code} missing authoritative path"
        record = sealed_catalog.get(code)
        assert record.authoritative_paths()
        for path in record.authoritative_paths():
            assert path.role in AUTHORITATIVE_ROLES or path.authority_class is AuthorityClass.EXCEPTION
            assert path.authority_class is not AuthorityClass.SECONDARY
            assert path.entry_url.startswith(("http://", "https://"))
            assert path.allowed_domains


def test_assert_catalog_invariants_passes(sealed_catalog: OfficialSourceCatalog) -> None:
    assert_catalog_invariants(sealed_catalog)


def test_dc_uses_dc_council_role(sealed_catalog: OfficialSourceCatalog) -> None:
    dc = sealed_catalog.get("DC")
    assert dc.name == "District of Columbia"
    roles = {path.role for path in dc.authoritative_paths()}
    assert SourceRole.DC_COUNCIL in roles
    assert any("dccouncil" in path.entry_url for path in dc.acquisition_paths)


def test_cached_loader_returns_same_invariants() -> None:
    a = get_official_source_catalog()
    b = get_official_source_catalog()
    assert a.postal_codes() == b.postal_codes()
    assert len(a.postal_codes()) == 51


def test_load_catalog_from_payload_round_trip(sealed_catalog: OfficialSourceCatalog) -> None:
    payload = sealed_catalog.to_dict()
    reloaded = load_official_source_catalog(payload=payload)
    assert reloaded.postal_codes() == sealed_catalog.postal_codes()
    assert reloaded.jurisdiction_count == 51


def test_catalog_rejects_wrong_schema_version() -> None:
    payload = _catalog_payload()
    payload["schema_version"] = "wrong"
    with pytest.raises(CatalogSchemaError):
        load_official_source_catalog(payload=payload)


def test_catalog_rejects_jurisdiction_without_authoritative_path() -> None:
    payload = _catalog_payload()
    # Replace AL authoritative path with secondary-only Justia path.
    for row in payload["jurisdictions"]:
        if row["postal_code"] == "AL":
            row["acquisition_paths"] = [
                {
                    "path_id": "al-justia-only",
                    "role": "secondary",
                    "authority_class": "secondary",
                    "provider": "justia",
                    "base_url": "https://law.justia.com",
                    "entry_url": "https://law.justia.com/codes/alabama/",
                    "allowed_domains": ["law.justia.com"],
                    "discovery_mode": "hierarchy",
                    "as_of_fields": ["retrieval_time"],
                }
            ]
            break
    with pytest.raises(MissingAuthoritativePathError):
        load_official_source_catalog(payload=payload)


def test_catalog_rejects_missing_dc() -> None:
    payload = _catalog_payload()
    payload["jurisdictions"] = [
        row for row in payload["jurisdictions"] if row["postal_code"] != "DC"
    ]
    payload["jurisdiction_count"] = 50
    with pytest.raises(CatalogSchemaError):
        load_official_source_catalog(payload=payload)


def test_catalog_rejects_secondary_host_marked_official() -> None:
    payload = _catalog_payload()
    for row in payload["jurisdictions"]:
        if row["postal_code"] == "OR":
            row["acquisition_paths"].append(
                {
                    "path_id": "or-justia-fake-official",
                    "role": "official_legislature",
                    "authority_class": "official",
                    "provider": "justia",
                    "base_url": "https://law.justia.com",
                    "entry_url": "https://law.justia.com/codes/oregon/",
                    "allowed_domains": ["law.justia.com"],
                    "discovery_mode": "hierarchy",
                    "as_of_fields": ["retrieval_time"],
                }
            )
            break
    with pytest.raises(DomainConstraintError):
        load_official_source_catalog(payload=payload)


# ---------------------------------------------------------------------------
# Mutable / secondary-only admission rejection
# ---------------------------------------------------------------------------


def test_mutable_reference_detection() -> None:
    assert is_mutable_reference("latest")
    assert is_mutable_reference("MAIN")
    assert is_mutable_reference("HEAD")
    assert is_mutable_reference("refs/heads/main")
    assert not is_mutable_reference("2024-ed")
    assert not is_mutable_reference("us/pl/118/45")
    assert not is_mutable_reference(None)
    with pytest.raises(MutableReferenceError):
        reject_mutable_reference("latest", field_name="release_point")


def test_secondary_host_markers() -> None:
    assert is_secondary_host("law.justia.com")
    assert is_secondary_host("codes.findlaw.com")
    assert not is_secondary_host("www.oregonlegislature.gov")
    assert not is_secondary_host("code.dccouncil.gov")


def test_admission_accepts_authoritative_path(
    sealed_catalog: OfficialSourceCatalog,
) -> None:
    or_record = sealed_catalog.get("OR")
    path_id = or_record.authoritative_paths()[0].path_id
    decision = require_authoritative_admission(
        "OR",
        [path_id],
        release_point="2023-ed",
        edition="2023",
        source_url=or_record.authoritative_paths()[0].entry_url,
        catalog=sealed_catalog,
    )
    assert decision.admitted is True
    assert decision.postal_code == "OR"
    assert path_id in decision.authoritative_path_ids
    assert decision.quarantine is False


def test_admission_rejects_mutable_release_point(
    sealed_catalog: OfficialSourceCatalog,
) -> None:
    ca = sealed_catalog.get("CA")
    path_id = ca.authoritative_paths()[0].path_id
    with pytest.raises(MutableReferenceError):
        evaluate_admission(
            AdmissionRequest(
                postal_code="CA",
                acquisition_path_ids=(path_id,),
                release_point="latest",
            ),
            catalog=sealed_catalog,
        )


def test_admission_rejects_mutable_edition_and_as_of(
    sealed_catalog: OfficialSourceCatalog,
) -> None:
    tx = sealed_catalog.get("TX")
    path_id = tx.authoritative_paths()[0].path_id
    with pytest.raises(MutableReferenceError):
        evaluate_admission(
            AdmissionRequest(
                postal_code="TX",
                acquisition_path_ids=(path_id,),
                edition="main",
            ),
            catalog=sealed_catalog,
        )
    with pytest.raises(MutableReferenceError):
        evaluate_admission(
            AdmissionRequest(
                postal_code="TX",
                acquisition_path_ids=(path_id,),
                as_of="HEAD",
            ),
            catalog=sealed_catalog,
        )


def test_admission_rejects_secondary_only(
    sealed_catalog: OfficialSourceCatalog,
) -> None:
    # Build an ephemeral catalog that adds a secondary path for AL but keeps official.
    payload = sealed_catalog.to_dict()
    for row in payload["jurisdictions"]:
        if row["postal_code"] == "AL":
            row["acquisition_paths"].append(
                {
                    "path_id": "al-justia-secondary",
                    "role": "secondary",
                    "authority_class": "secondary",
                    "provider": "justia",
                    "base_url": "https://law.justia.com",
                    "entry_url": "https://law.justia.com/codes/alabama/",
                    "allowed_domains": ["law.justia.com"],
                    "discovery_mode": "hierarchy",
                    "as_of_fields": ["retrieval_time"],
                }
            )
            break
    catalog = load_official_source_catalog(payload=payload)
    with pytest.raises(SecondaryOnlyAdmissionError):
        evaluate_admission(
            AdmissionRequest(
                postal_code="AL",
                acquisition_path_ids=("al-justia-secondary",),
            ),
            catalog=catalog,
        )


def test_secondary_only_may_quarantine_but_not_admit(
    sealed_catalog: OfficialSourceCatalog,
) -> None:
    payload = sealed_catalog.to_dict()
    for row in payload["jurisdictions"]:
        if row["postal_code"] == "GA":
            row["acquisition_paths"].append(
                {
                    "path_id": "ga-justia-secondary",
                    "role": "secondary",
                    "authority_class": "secondary",
                    "provider": "justia",
                    "base_url": "https://law.justia.com",
                    "entry_url": "https://law.justia.com/codes/georgia/",
                    "allowed_domains": ["law.justia.com"],
                    "discovery_mode": "hierarchy",
                    "as_of_fields": ["retrieval_time"],
                }
            )
            break
    catalog = load_official_source_catalog(payload=payload)
    decision = evaluate_admission(
        AdmissionRequest(
            postal_code="GA",
            acquisition_path_ids=("ga-justia-secondary",),
            allow_secondary_quarantine=True,
        ),
        catalog=catalog,
    )
    assert decision.admitted is False
    assert decision.quarantine is True
    with pytest.raises(SecondaryOnlyAdmissionError):
        require_authoritative_admission(
            "GA",
            ["ga-justia-secondary"],
            catalog=catalog,
        )


def test_admission_rejects_secondary_source_url_for_official_path(
    sealed_catalog: OfficialSourceCatalog,
) -> None:
    al = sealed_catalog.get("AL")
    path_id = al.authoritative_paths()[0].path_id
    with pytest.raises(DomainConstraintError):
        evaluate_admission(
            AdmissionRequest(
                postal_code="AL",
                acquisition_path_ids=(path_id,),
                source_url="https://law.justia.com/codes/alabama/title-13a/",
            ),
            catalog=sealed_catalog,
        )


def test_admission_requires_path_ids(
    sealed_catalog: OfficialSourceCatalog,
) -> None:
    with pytest.raises(MissingAuthoritativePathError):
        evaluate_admission(
            AdmissionRequest(postal_code="FL", acquisition_path_ids=()),
            catalog=sealed_catalog,
        )


def test_acquisition_path_is_authoritative_helpers() -> None:
    official = AcquisitionPath.from_mapping(
        {
            "path_id": "demo-official",
            "role": "official_reviser",
            "authority_class": "official",
            "provider": "demo",
            "base_url": "https://www.revisor.mn.gov",
            "entry_url": "https://www.revisor.mn.gov/statutes/",
            "allowed_domains": ["www.revisor.mn.gov", "revisor.mn.gov"],
            "discovery_mode": "hierarchy",
            "as_of_fields": ["edition", "retrieval_time"],
        }
    )
    assert official.is_authoritative() is True
    secondary = AcquisitionPath.from_mapping(
        {
            "path_id": "demo-secondary",
            "role": "secondary",
            "authority_class": "secondary",
            "provider": "justia",
            "base_url": "https://law.justia.com",
            "entry_url": "https://law.justia.com/codes/minnesota/",
            "allowed_domains": ["law.justia.com"],
            "discovery_mode": "hierarchy",
            "as_of_fields": ["retrieval_time"],
        }
    )
    assert secondary.is_authoritative() is False


def test_every_sealed_jurisdiction_admits_on_its_authoritative_path(
    sealed_catalog: OfficialSourceCatalog,
) -> None:
    """Production gate: every one of the 51 codes has a usable admission path."""

    for record in sealed_catalog.jurisdictions:
        path = record.authoritative_paths()[0]
        decision = evaluate_admission(
            AdmissionRequest(
                postal_code=record.postal_code,
                acquisition_path_ids=(path.path_id,),
                release_point="2024-official-edition",
                edition="2024",
                source_url=path.entry_url,
            ),
            catalog=sealed_catalog,
        )
        assert decision.admitted is True
        assert decision.postal_code == record.postal_code
