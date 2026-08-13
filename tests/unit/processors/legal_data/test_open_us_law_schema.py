"""Unit tests for the Open US Law identity schema (OUL-005).

Acceptance: state statutes use stable jurisdiction, hierarchy, edition,
source CID, entry CID, and text hash fields; PR, federal, constitutions,
historical, recovery, and quarantine rows are explicit non-default
configurations.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    ALL_CONFIGURATION_NAMES,
    DEFAULT_CONFIGURATION,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    DEFAULT_MODEL_TOKEN_CEILING,
    EXACT_51_JURISDICTION_CODES,
    EXACT_51_JURISDICTIONS,
    EXPECTED_JURISDICTION_COUNT,
    FEDERAL_JURISDICTION_CODE,
    KNOWN_NON_DEFAULT_JURISDICTIONS,
    LEGAL_ID_PREFIX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    NON_DEFAULT_CONFIGURATION_NAMES,
    PUERTO_RICO_CODE,
    RELEASE_PROFILE,
    RELEASE_SCHEMA_PATH,
    REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS,
    SCHEMA_VERSION,
    SOURCE_BUCKET,
    TASK_ID,
    AdmissionStatus,
    ConfigurationBoundaryError,
    ConfigurationDescriptor,
    DocumentKind,
    Exact51GateError,
    Hierarchy,
    InvalidDigestError,
    JurisdictionSetError,
    MissingIdentityFieldError,
    MutableReferenceError,
    OpenUsLawSchemaError,
    PositionalIdentityError,
    ReleaseConfiguration,
    ReleaseIdentityManifest,
    StatuteIdentity,
    StatuteStatus,
    build_legal_id,
    classify_configuration,
    compute_text_hash,
    configuration_boundary_policy,
    configuration_satisfies_exact_51,
    content_sha256,
    default_configuration_policy,
    example_constitution_payload,
    example_default_statute_payload,
    example_federal_payload,
    example_historical_payload,
    example_mixed_rows,
    example_puerto_rico_payload,
    example_quarantine_payload,
    example_recovery_payload,
    example_release_manifest,
    infer_configuration,
    load_release_schema,
    non_default_configuration_policy,
    normalize_edition,
    normalize_jurisdiction_code,
    normalize_section_token,
    parse_legal_id,
    partition_by_configuration,
    physical_bounds_policy,
    reject_positional_durable_identity,
    require_immutable_revision,
    validate_against_release_schema,
    validate_corpus_identity,
    validate_default_statute_identity,
    validate_entry_cid,
    validate_exact_51_gate,
    validate_jurisdiction_set,
    validate_legal_id,
    validate_release_manifest,
    validate_text_hash,
)

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None  # type: ignore[misc, assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _digest(label: str) -> str:
    return content_sha256(label)


# ---------------------------------------------------------------------------
# Schema metadata / constants
# ---------------------------------------------------------------------------


def test_schema_constants_match_sealed_policy():
    assert SCHEMA_VERSION == "open-us-law-identity-schema-v1"
    assert RELEASE_PROFILE == "open-us-law-sparse-graphrag/v1"
    assert TASK_ID == "OUL-005"
    assert DEFAULT_DATASET_REPO_ID == "justicedao/open-us-law-sparse-graphrag"
    assert SOURCE_BUCKET == "justicedao/open-us-law-bucket"
    assert DEFAULT_CONFIGURATION == "state_statutes_exact_51"
    assert DEFAULT_EMBEDDING_MODEL_ID == "thenlper/gte-small"
    assert DEFAULT_EMBEDDING_MODEL_REVISION == (
        "17e1f347d17fe144873b1201da91788898c639cd"
    )
    assert DEFAULT_EMBEDDING_DIMENSION == 384
    assert DEFAULT_MODEL_TOKEN_CEILING == 512
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert LEGAL_ID_PREFIX == "oul"
    assert REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS == (
        "jurisdiction_code",
        "hierarchy",
        "edition",
        "source_cid",
        "entry_cid",
        "text_hash",
    )
    bounds = physical_bounds_policy()
    assert bounds["max_rows_per_physical_shard"] == 4096
    assert bounds["model_token_ceiling"] == 512
    assert bounds["embedding_dimension"] == 384


def test_exact_51_set_is_fifty_states_plus_dc_without_pr_or_federal():
    assert len(EXACT_51_JURISDICTION_CODES) == EXPECTED_JURISDICTION_COUNT == 51
    assert len(EXACT_51_JURISDICTIONS) == 51
    assert "DC" in EXACT_51_JURISDICTIONS
    assert "CA" in EXACT_51_JURISDICTIONS
    assert "OR" in EXACT_51_JURISDICTIONS
    assert "GA" in EXACT_51_JURISDICTIONS
    assert "NC" in EXACT_51_JURISDICTIONS
    assert PUERTO_RICO_CODE not in EXACT_51_JURISDICTIONS
    assert FEDERAL_JURISDICTION_CODE not in EXACT_51_JURISDICTIONS
    assert KNOWN_NON_DEFAULT_JURISDICTIONS == frozenset({"PR", "US"})
    validate_jurisdiction_set(EXACT_51_JURISDICTION_CODES)


def test_configuration_boundary_policy_lists_every_non_default():
    policy = configuration_boundary_policy()
    assert policy["default_configuration"] == DEFAULT_CONFIGURATION
    assert policy["non_default_configurations"] == list(NON_DEFAULT_CONFIGURATION_NAMES)
    assert set(policy["all_configurations"]) == set(ALL_CONFIGURATION_NAMES)
    assert set(NON_DEFAULT_CONFIGURATION_NAMES) == {
        "federal_uscode",
        "puerto_rico",
        "constitutions",
        "historical",
        "recovery",
        "quarantine",
    }
    default = default_configuration_policy()
    assert default["satisfies_exact_51_gate"] is True
    assert default["required_identity_fields"] == list(
        REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS
    )
    separate = non_default_configuration_policy()
    for name in NON_DEFAULT_CONFIGURATION_NAMES:
        assert separate[name]["default"] is False
        assert separate[name]["satisfies_exact_51_gate"] is False
        assert configuration_satisfies_exact_51(name) is False
    assert configuration_satisfies_exact_51(DEFAULT_CONFIGURATION) is True


# ---------------------------------------------------------------------------
# Default statute identity fields
# ---------------------------------------------------------------------------


def test_example_default_statute_has_required_identity_fields():
    payload = example_default_statute_payload()
    validated = validate_default_statute_identity(payload)
    for field_name in REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS:
        assert validated[field_name] not in (None, "")
    assert validated["jurisdiction_code"] == "OR"
    assert validated["hierarchy"]["title"] == "123"
    assert validated["hierarchy"]["section"] == "456"
    assert validated["edition"] == "2024-official"
    assert validated["source_cid"] == payload["source_cid"]
    assert validated["entry_cid"] == payload["entry_cid"]
    assert validated["text_hash"] == compute_text_hash(payload["text"])
    assert validated["configuration"] == DEFAULT_CONFIGURATION
    assert validated["satisfies_exact_51_gate"] is True
    assert validated["legal_id"].startswith("oul:statute:OR:")


@pytest.mark.parametrize(
    "field_name",
    list(REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS),
)
def test_default_statute_rejects_missing_identity_field(field_name: str):
    payload = example_default_statute_payload()
    if field_name == "jurisdiction_code":
        payload["jurisdiction_code"] = ""
        payload.pop("jurisdiction", None)
    elif field_name == "hierarchy":
        payload["hierarchy"] = {}
        payload.pop("section", None)
    else:
        payload[field_name] = ""
    with pytest.raises((MissingIdentityFieldError, OpenUsLawSchemaError)):
        validate_default_statute_identity(payload)


def test_default_statute_text_hash_must_match_body():
    payload = example_default_statute_payload()
    payload["text_hash"] = compute_text_hash("different body")
    with pytest.raises(InvalidDigestError):
        validate_default_statute_identity(payload)


def test_jurisdiction_alias_is_accepted_as_jurisdiction_code():
    payload = example_default_statute_payload()
    payload["jurisdiction"] = payload.pop("jurisdiction_code")
    validated = validate_default_statute_identity(payload)
    assert validated["jurisdiction_code"] == "OR"


def test_dc_is_a_first_class_default_jurisdiction():
    payload = example_default_statute_payload(jurisdiction_code="DC")
    validated = validate_default_statute_identity(payload)
    assert validated["jurisdiction_code"] == "DC"
    assert validated["legal_id"].startswith("oul:statute:DC:")
    assert normalize_jurisdiction_code("dc") == "DC"


def test_statute_identity_round_trips_and_is_frozen():
    payload = example_default_statute_payload()
    record = StatuteIdentity.from_mapping(payload)
    encoded = record.to_dict()
    again = StatuteIdentity.from_mapping(encoded)
    assert again.legal_id == record.legal_id
    assert again.entry_cid == record.entry_cid
    assert again.source_cid == record.source_cid
    assert again.text_hash == record.text_hash
    assert again.configuration is ReleaseConfiguration.STATE_STATUTES_EXACT_51
    with pytest.raises(FrozenInstanceError):
        record.edition = "mutated"  # type: ignore[misc]


def test_legal_id_is_stable_and_parseable():
    legal_id = build_legal_id(
        document_kind="statute",
        jurisdiction_code="OR",
        code_family="ors",
        hierarchy={"title": "123", "section": "456"},
        edition="2024-official",
    )
    assert legal_id == "oul:statute:OR:ors:123:456;edition=2024-official"
    parsed = parse_legal_id(legal_id)
    assert parsed["jurisdiction_code"] == "OR"
    assert parsed["code_family"] == "ors"
    assert parsed["hierarchy"].section == "456"
    assert parsed["edition"] == "2024-official"
    assert validate_legal_id(legal_id) == legal_id


def test_unicode_dash_section_is_not_truncated():
    assert normalize_section_token("1001–1003") == "1001-1003"
    legal_id = build_legal_id(
        document_kind="statute",
        jurisdiction_code="OR",
        code_family="ors",
        hierarchy={"title": "1", "section": "1001–1003"},
        edition="2024-official",
    )
    assert "1001-1003" in legal_id
    assert legal_id != build_legal_id(
        document_kind="statute",
        jurisdiction_code="OR",
        code_family="ors",
        hierarchy={"title": "1", "section": "1001"},
        edition="2024-official",
    )


# ---------------------------------------------------------------------------
# Positional identity / mutable pins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    ["row-0", "row-12", "row-N", "row_3", "document_index_4", "idx-9", "pos-1"],
)
def test_rejects_positional_durable_identity(token: str):
    with pytest.raises(PositionalIdentityError):
        reject_positional_durable_identity(token, name="entry_cid")
    with pytest.raises(PositionalIdentityError):
        validate_entry_cid(token)


def test_document_index_alone_cannot_identify_a_default_row():
    with pytest.raises(PositionalIdentityError):
        validate_default_statute_identity({"document_index": 42})


def test_rejects_positional_legal_id():
    with pytest.raises(PositionalIdentityError):
        validate_legal_id("row-99")


@pytest.mark.parametrize("edition", ["latest", "current", "main", "HEAD"])
def test_rejects_mutable_edition_pins(edition: str):
    with pytest.raises(MutableReferenceError):
        normalize_edition(edition)


def test_rejects_mutable_model_revision():
    with pytest.raises(MutableReferenceError):
        require_immutable_revision("latest")


# ---------------------------------------------------------------------------
# Non-default configuration boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factory", "expected"),
    [
        (example_federal_payload, "federal_uscode"),
        (example_puerto_rico_payload, "puerto_rico"),
        (example_constitution_payload, "constitutions"),
        (example_historical_payload, "historical"),
        (example_recovery_payload, "recovery"),
        (example_quarantine_payload, "quarantine"),
    ],
)
def test_non_default_rows_classify_to_explicit_configurations(factory, expected):
    payload = factory()
    assert infer_configuration(payload).value == expected
    assert classify_configuration(payload).value == expected
    validated = validate_corpus_identity(payload)
    assert validated["configuration"] == expected
    assert validated["satisfies_exact_51_gate"] is False
    with pytest.raises(ConfigurationBoundaryError):
        validate_default_statute_identity(payload)


def test_oregon_constitution_is_not_default_even_though_or_is_exact_51():
    payload = example_constitution_payload(jurisdiction_code="OR")
    assert payload["jurisdiction_code"] == "OR"
    validated = validate_corpus_identity(payload)
    assert validated["configuration"] == "constitutions"
    assert validated["satisfies_exact_51_gate"] is False
    assert validated["document_kind"] == DocumentKind.CONSTITUTION.value


def test_historical_oregon_statute_is_not_default():
    payload = example_historical_payload(jurisdiction_code="OR")
    validated = validate_corpus_identity(payload)
    assert validated["jurisdiction_code"] == "OR"
    assert validated["configuration"] == "historical"
    assert validated["status"] == StatuteStatus.HISTORICAL.value
    assert validated["satisfies_exact_51_gate"] is False


def test_cannot_stamp_default_configuration_on_pr_or_federal_rows():
    pr = example_puerto_rico_payload()
    pr["configuration"] = DEFAULT_CONFIGURATION
    with pytest.raises(ConfigurationBoundaryError):
        classify_configuration(pr)

    federal = example_federal_payload()
    federal["configuration"] = DEFAULT_CONFIGURATION
    with pytest.raises(ConfigurationBoundaryError):
        classify_configuration(federal)


def test_pr_and_us_are_rejected_from_the_exact_51_jurisdiction_helper():
    with pytest.raises(JurisdictionSetError):
        normalize_jurisdiction_code("PR", allow_non_default=False)
    with pytest.raises(JurisdictionSetError):
        normalize_jurisdiction_code("US", allow_non_default=False)
    assert normalize_jurisdiction_code("PR") == "PR"
    assert normalize_jurisdiction_code("USA") == "US"
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(list(EXACT_51_JURISDICTIONS) + ["PR"])
    with pytest.raises(JurisdictionSetError):
        validate_jurisdiction_set(sorted(EXACT_51_JURISDICTIONS - {"DC"}))


def test_operator_may_quarantine_an_otherwise_default_row():
    payload = example_default_statute_payload()
    payload["configuration"] = "quarantine"
    payload["admission_status"] = AdmissionStatus.QUARANTINED.value
    validated = validate_corpus_identity(payload)
    assert validated["configuration"] == "quarantine"
    assert validated["satisfies_exact_51_gate"] is False


def test_non_default_configurations_cannot_satisfy_exact_51_gate():
    for name in NON_DEFAULT_CONFIGURATION_NAMES:
        descriptor = ConfigurationDescriptor(
            name=name,
            default=False,
            satisfies_exact_51_gate=False,
            viewer_visible=name not in {"recovery", "quarantine"},
            description=f"test {name}",
        )
        assert descriptor.satisfies_exact_51_gate is False
        with pytest.raises(Exact51GateError):
            ConfigurationDescriptor(
                name=name,
                default=False,
                satisfies_exact_51_gate=True,
                viewer_visible=False,
                description=f"illegal {name}",
            )
        with pytest.raises(ConfigurationBoundaryError):
            ConfigurationDescriptor(
                name=name,
                default=True,
                satisfies_exact_51_gate=False,
                viewer_visible=False,
                description=f"illegal default {name}",
            )


def test_partition_mixed_rows_keeps_non_default_out_of_default():
    partitioned = partition_by_configuration(example_mixed_rows())
    assert len(partitioned[DEFAULT_CONFIGURATION]) == 1
    assert partitioned[DEFAULT_CONFIGURATION][0]["jurisdiction_code"] == "OR"
    assert len(partitioned["federal_uscode"]) == 1
    assert len(partitioned["puerto_rico"]) == 1
    assert len(partitioned["constitutions"]) == 1
    assert len(partitioned["historical"]) == 1
    assert len(partitioned["recovery"]) == 1
    assert len(partitioned["quarantine"]) == 1


def test_exact_51_gate_ignores_non_default_rows_and_rejects_leaks():
    rows = [
        example_default_statute_payload(jurisdiction_code="OR"),
        example_default_statute_payload(jurisdiction_code="CA"),
        example_federal_payload(),
        example_puerto_rico_payload(),
        example_constitution_payload(),
        example_historical_payload(),
        example_recovery_payload(),
        example_quarantine_payload(),
    ]
    result = validate_exact_51_gate(rows)
    assert result["default_row_count"] == 2
    assert result["default_jurisdictions"] == ["CA", "OR"]
    assert result["non_default_satisfies_gate"] is False
    assert result["non_default_counts"]["federal_uscode"] == 1
    assert result["non_default_counts"]["puerto_rico"] == 1
    assert "DC" in result["missing_jurisdictions"]

    leaked = example_puerto_rico_payload()
    leaked["configuration"] = DEFAULT_CONFIGURATION
    with pytest.raises(ConfigurationBoundaryError):
        validate_exact_51_gate([example_default_statute_payload(), leaked])


def test_exact_51_gate_requires_full_coverage_when_asked():
    one = [example_default_statute_payload()]
    with pytest.raises(Exact51GateError):
        validate_exact_51_gate(one, require_full_coverage=True)

    full = [
        example_default_statute_payload(jurisdiction_code=code, title="1", section="1")
        for code in EXACT_51_JURISDICTION_CODES
    ]
    full.extend(example_mixed_rows()[1:])
    result = validate_exact_51_gate(full, require_full_coverage=True)
    assert result["closed"] is True
    assert result["default_row_count"] == 51
    assert result["missing_jurisdictions"] == []
    assert set(result["default_jurisdictions"]) == EXACT_51_JURISDICTIONS


# ---------------------------------------------------------------------------
# Release manifest + JSON Schema
# ---------------------------------------------------------------------------


def test_release_schema_file_exists_and_matches_python_constants():
    assert RELEASE_SCHEMA_PATH.is_file()
    schema = load_release_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    assert schema["properties"]["release_profile"]["const"] == RELEASE_PROFILE
    assert schema["properties"]["task_id"]["const"] == TASK_ID
    assert schema["properties"]["dataset_repo_id"]["const"] == DEFAULT_DATASET_REPO_ID
    assert schema["properties"]["default_configuration"]["const"] == DEFAULT_CONFIGURATION
    assert schema["properties"]["identity_fields"]["const"] == list(
        REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS
    )
    assert schema["properties"]["model_id"]["const"] == DEFAULT_EMBEDDING_MODEL_ID
    assert schema["properties"]["model_revision"]["const"] == (
        DEFAULT_EMBEDDING_MODEL_REVISION
    )
    assert schema["properties"]["model_token_ceiling"]["const"] == 512
    assert schema["properties"]["max_rows_per_physical_shard"]["const"] == 4096
    codes = schema["$defs"]["jurisdictionSet"]["properties"]["required_codes"]
    jurisdiction_ref = codes["items"]["$ref"]
    assert jurisdiction_ref == "#/$defs/exact51Jurisdiction"
    exact_enum = schema["$defs"]["exact51Jurisdiction"]["enum"]
    assert set(exact_enum) == EXACT_51_JURISDICTIONS
    assert "PR" not in exact_enum
    assert "US" not in exact_enum
    assert set(schema["$defs"]["nonDefaultConfigurationName"]["enum"]) == set(
        NON_DEFAULT_CONFIGURATION_NAMES
    )


def test_example_release_manifest_validates_against_json_schema():
    payload = example_release_manifest()
    encoded = validate_release_manifest(payload)
    assert encoded["default_configuration"] == DEFAULT_CONFIGURATION
    assert encoded["extras_in_default_allowed"] is False
    names = [item["name"] for item in encoded["configurations"]]
    assert names[0] == DEFAULT_CONFIGURATION
    assert set(names) == set(ALL_CONFIGURATION_NAMES)
    for item in encoded["configurations"]:
        if item["name"] == DEFAULT_CONFIGURATION:
            assert item["default"] is True
            assert item["satisfies_exact_51_gate"] is True
        else:
            assert item["default"] is False
            assert item["satisfies_exact_51_gate"] is False
    errors = validate_against_release_schema(encoded)
    assert errors == []
    if Draft202012Validator is not None:
        Draft202012Validator(load_release_schema()).validate(encoded)


def test_example_release_manifest_with_mixed_rows_validates():
    payload = example_release_manifest(include_example_rows=True)
    encoded = validate_release_manifest(payload)
    assert len(encoded["rows"]) == 7
    by_config = {row["configuration"] for row in encoded["rows"]}
    assert DEFAULT_CONFIGURATION in by_config
    assert by_config >= set(NON_DEFAULT_CONFIGURATION_NAMES)
    assert validate_against_release_schema(encoded) == []


def test_json_schema_rejects_non_default_as_default_configuration():
    payload = example_release_manifest()
    payload["default_configuration"] = "federal_uscode"
    if "manifest_digest" in payload:
        payload.pop("manifest_digest", None)
    with pytest.raises((ConfigurationBoundaryError, OpenUsLawSchemaError)):
        validate_release_manifest(payload)
    raw = example_release_manifest()
    raw["default_configuration"] = "puerto_rico"
    errors = validate_against_release_schema(raw)
    assert errors


def test_json_schema_rejects_pr_row_in_default_configuration():
    raw = example_release_manifest(include_example_rows=True)
    for row in raw["rows"]:
        if row["configuration"] == "puerto_rico":
            row["configuration"] = DEFAULT_CONFIGURATION
            row["satisfies_exact_51_gate"] = True
            break
    errors = validate_against_release_schema(raw)
    assert errors


def test_release_manifest_rejects_missing_non_default_configuration():
    payload = example_release_manifest()
    payload["configurations"] = [
        item
        for item in payload["configurations"]
        if item["name"] != "quarantine"
    ]
    with pytest.raises(ConfigurationBoundaryError):
        ReleaseIdentityManifest.from_mapping(payload)


def test_release_manifest_round_trips():
    payload = example_release_manifest(include_example_rows=True)
    record = ReleaseIdentityManifest.from_mapping(payload)
    encoded = record.to_dict()
    again = ReleaseIdentityManifest.from_mapping(encoded)
    assert again.dataset_repo_id == DEFAULT_DATASET_REPO_ID
    assert again.default_configuration == DEFAULT_CONFIGURATION
    assert len(again.configurations) == 7
    assert again.identity_fields == REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS


def test_schema_file_is_valid_draft_2020_12():
    if Draft202012Validator is None:
        pytest.skip("jsonschema is not installed")
    schema = json.loads(Path(RELEASE_SCHEMA_PATH).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


# ---------------------------------------------------------------------------
# Hierarchy helpers
# ---------------------------------------------------------------------------


def test_hierarchy_requires_section_for_default_statutes():
    payload = example_default_statute_payload()
    payload["hierarchy"] = {"title": "123"}
    with pytest.raises(MissingIdentityFieldError):
        validate_default_statute_identity(payload)


def test_hierarchy_path_round_trip():
    hierarchy = Hierarchy.from_mapping({"title": "12", "chapter": "3", "section": "45(a)"})
    assert hierarchy.path() == "12:3:45(a)"
    assert hierarchy.to_dict()["section"] == "45(a)"
    from_path = Hierarchy.from_mapping("12:3:45(a)")
    assert from_path.section == "45(a)"
    assert from_path.title == "12"


def test_text_hash_is_nfc_sha256():
    text = "café"
    digest = compute_text_hash(text)
    assert validate_text_hash(digest) == digest
    assert len(digest) == 64
    with pytest.raises(InvalidDigestError):
        validate_text_hash("not-a-hash")
