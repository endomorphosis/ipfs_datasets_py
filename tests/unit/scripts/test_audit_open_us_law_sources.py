"""Unit tests for the OUL-002 exact-51 official-source admission matrix."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.ops.legal_data.audit_open_us_law_sources import (
    BLOCKED_CODES,
    DISPOSITION_BLOCKED,
    DISPOSITION_CANDIDATE,
    DISPOSITION_LINK_REPAIR,
    DISPOSITION_QUARANTINE,
    FAIL_CLOSED_JURISDICTION_CODES,
    JURISDICTION_COUNT,
    LICENSE_REF_DIGEST,
    LINK_REPAIR_CODES,
    QUARANTINE_CODES,
    REQUIRED_JURISDICTION_CODES,
    AuditError,
    audit_source_admission,
    build_source_admission_payload,
    check_committed_matrix,
    default_matrix_path,
    default_schema_path,
    encode_source_admission,
    expected_jurisdiction_codes,
    expected_seed_disposition,
    is_official_source_url,
    load_source_admission,
    main,
    sha256_json,
    validate_source_admission,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _row(payload: dict, code: str) -> dict:
    return next(
        item for item in payload["jurisdictions"] if item["jurisdiction_code"] == code
    )


def _reseal(payload: dict) -> dict:
    body = {key: value for key, value in payload.items() if key != "matrix_digest_sha256"}
    payload["matrix_digest_sha256"] = sha256_json(body)
    return payload


def _mutated(payload: dict) -> dict:
    return _reseal(copy.deepcopy(payload))


def test_expected_jurisdiction_codes_are_exact_51_including_dc_once() -> None:
    codes = expected_jurisdiction_codes()
    assert codes == REQUIRED_JURISDICTION_CODES
    assert len(codes) == JURISDICTION_COUNT == 51
    assert len(set(codes)) == 51
    assert codes.count("DC") == 1
    assert "PR" not in codes
    assert "US" not in codes
    for code in ("AL", "CA", "GA", "NC", "NY", "TX", "WA", "DC"):
        assert code in codes


def test_seed_dispositions_match_plan_cohorts() -> None:
    assert expected_seed_disposition("GA") == DISPOSITION_BLOCKED
    assert expected_seed_disposition("NC") == DISPOSITION_BLOCKED
    assert BLOCKED_CODES == frozenset(FAIL_CLOSED_JURISDICTION_CODES)
    for code in QUARANTINE_CODES:
        assert expected_seed_disposition(code) == DISPOSITION_QUARANTINE
    for code in LINK_REPAIR_CODES:
        assert expected_seed_disposition(code) == DISPOSITION_LINK_REPAIR
    candidates = [
        code
        for code in REQUIRED_JURISDICTION_CODES
        if code not in BLOCKED_CODES | QUARANTINE_CODES | LINK_REPAIR_CODES
    ]
    assert len(candidates) == 36
    for code in candidates:
        assert expected_seed_disposition(code) == DISPOSITION_CANDIDATE


def test_official_source_url_rejects_linkless_values() -> None:
    assert is_official_source_url("https://www.legis.ga.gov/legislation/laws.html")
    assert is_official_source_url("http://www.leg.state.fl.us/Statutes/")
    assert not is_official_source_url("")
    assert not is_official_source_url("   ")
    assert not is_official_source_url("https://")
    assert not is_official_source_url("ftp://example.gov/statutes")
    assert not is_official_source_url("not-a-url")


def test_committed_matrix_matches_deterministic_builder() -> None:
    committed = default_matrix_path().read_bytes()
    generated = encode_source_admission(build_source_admission_payload())
    assert committed == generated


def test_committed_matrix_passes_require_51_audit() -> None:
    report = check_committed_matrix(require_51=True)
    assert report["status"] == "passed"
    assert report["exact_51"] is True
    assert report["dc_counted_once"] is True
    assert report["jurisdiction_count"] == 51
    assert report["jurisdiction_codes"] == list(REQUIRED_JURISDICTION_CODES)
    assert report["authorizing_for_publication"] is False
    assert "GA" in report["fail_closed_jurisdiction_codes"]
    assert "NC" in report["fail_closed_jurisdiction_codes"]
    assert report["publication_admitted_jurisdiction_codes"] == []


def test_every_row_has_required_admission_fields() -> None:
    payload = load_source_admission()
    assert payload["jurisdiction_count"] == 51
    assert len(payload["jurisdictions"]) == 51
    for row in payload["jurisdictions"]:
        assert set(row) == {
            "jurisdiction_code",
            "name",
            "official_authority",
            "rights_scope",
            "attribution_duty",
            "frontier_method",
            "seed_disposition",
        }
        authority = row["official_authority"]
        assert authority["authority_class"] == "official"
        assert is_official_source_url(authority["entry_url"])
        assert is_official_source_url(authority["base_url"])
        assert authority["allowed_domains"]
        rights = row["rights_scope"]
        assert rights["content_scope"] == "statutory_text"
        assert rights["license_id"] == "LicenseRef-US-State-Statutory-Text"
        assert rights["legal_basis"] == "government_edicts_doctrine"
        assert rights["license_ref_digest_sha256"] == LICENSE_REF_DIGEST
        duty = row["attribution_duty"]
        assert duty["required"] is True
        assert authority["name"] in duty["notice"]
        frontier = row["frontier_method"]
        assert frontier["closed_frontier_required"] is True
        assert frontier["method_id"]
        assert frontier["discovery_mode"] in {
            "api",
            "hierarchy",
            "bundle",
            "pagination",
            "mixed",
        }
        disposition = row["seed_disposition"]
        assert disposition["disposition"] == expected_seed_disposition(
            row["jurisdiction_code"]
        )
        assert disposition["bucket_seed_admissible"] is False
        assert disposition["publication_admissible"] is False
        assert disposition["official_replacement_evidence"] is None


def test_ga_and_nc_are_fail_closed_without_replacement_evidence() -> None:
    payload = load_source_admission()
    for code in ("GA", "NC"):
        row = _row(payload, code)
        disposition = row["seed_disposition"]
        assert disposition["disposition"] == DISPOSITION_BLOCKED
        assert disposition["fail_closed"] is True
        assert disposition["bucket_seed_admissible"] is False
        assert disposition["publication_admissible"] is False
        assert disposition["official_replacement_evidence_required"] is True
        assert disposition["official_replacement_evidence_present"] is False
        assert "official replacement" in disposition["reason"]


def test_schema_file_is_present_and_names_fail_closed_contract() -> None:
    schema = json.loads(default_schema_path().read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == "open-us-law-source-admission-v1"
    assert schema["properties"]["jurisdiction_count"]["const"] == 51
    defs = schema["$defs"]
    assert "officialAuthority" in defs
    assert "rightsScope" in defs
    assert "attributionDuty" in defs
    assert "frontierMethod" in defs
    assert "seedDisposition" in defs
    assert DISPOSITION_BLOCKED in defs["seedDisposition"]["properties"]["disposition"]["enum"]


def test_missing_jurisdiction_fails() -> None:
    payload = _mutated(build_source_admission_payload())
    payload["jurisdictions"] = [
        row for row in payload["jurisdictions"] if row["jurisdiction_code"] != "DC"
    ]
    payload["jurisdiction_count"] = 50
    _reseal(payload)
    with pytest.raises(AuditError, match="exact-51|DC"):
        validate_source_admission(payload, require_51=True)


def test_extra_jurisdiction_fails() -> None:
    payload = _mutated(build_source_admission_payload())
    extra = copy.deepcopy(_row(payload, "AL"))
    extra["jurisdiction_code"] = "PR"
    extra["name"] = "Puerto Rico"
    payload["jurisdictions"].append(extra)
    payload["jurisdiction_count"] = 52
    _reseal(payload)
    with pytest.raises(AuditError, match="excluded|exact-51"):
        validate_source_admission(payload, require_51=True)


def test_duplicate_dc_fails() -> None:
    payload = _mutated(build_source_admission_payload())
    payload["jurisdictions"].append(copy.deepcopy(_row(payload, "DC")))
    payload["jurisdiction_count"] = 52
    _reseal(payload)
    with pytest.raises(AuditError, match="unique|DC"):
        validate_source_admission(payload, require_51=True)


def test_nonofficial_row_fails_closed() -> None:
    payload = _mutated(build_source_admission_payload())
    _row(payload, "OR")["official_authority"]["authority_class"] = "commercial"
    _reseal(payload)
    with pytest.raises(AuditError, match="nonofficial"):
        validate_source_admission(payload, require_51=True)


def test_linkless_row_fails_closed() -> None:
    payload = _mutated(build_source_admission_payload())
    _row(payload, "WY")["official_authority"]["entry_url"] = ""
    _reseal(payload)
    with pytest.raises(AuditError, match="linkless"):
        validate_source_admission(payload, require_51=True)


def test_ga_admitted_without_replacement_evidence_fails() -> None:
    payload = _mutated(build_source_admission_payload())
    ga = _row(payload, "GA")
    ga["seed_disposition"]["fail_closed"] = False
    ga["seed_disposition"]["bucket_seed_admissible"] = True
    ga["seed_disposition"]["publication_admissible"] = True
    payload["publication_admitted_jurisdiction_codes"] = ["GA"]
    _reseal(payload)
    with pytest.raises(AuditError, match="GA"):
        validate_source_admission(payload, require_51=True)


def test_nc_admitted_without_replacement_evidence_fails() -> None:
    payload = _mutated(build_source_admission_payload())
    nc = _row(payload, "NC")
    nc["seed_disposition"]["disposition"] = DISPOSITION_CANDIDATE
    nc["seed_disposition"]["fail_closed"] = False
    _reseal(payload)
    with pytest.raises(AuditError, match="NC"):
        validate_source_admission(payload, require_51=True)


def test_missing_rights_scope_fails() -> None:
    payload = _mutated(build_source_admission_payload())
    del _row(payload, "TX")["rights_scope"]
    _reseal(payload)
    with pytest.raises(AuditError, match="rights_scope"):
        validate_source_admission(payload, require_51=True)


def test_missing_attribution_duty_fails() -> None:
    payload = _mutated(build_source_admission_payload())
    del _row(payload, "CA")["attribution_duty"]
    _reseal(payload)
    with pytest.raises(AuditError, match="attribution_duty"):
        validate_source_admission(payload, require_51=True)


def test_missing_frontier_method_fails() -> None:
    payload = _mutated(build_source_admission_payload())
    del _row(payload, "NY")["frontier_method"]
    _reseal(payload)
    with pytest.raises(AuditError, match="frontier_method"):
        validate_source_admission(payload, require_51=True)


def test_wrong_quarantine_disposition_fails() -> None:
    payload = _mutated(build_source_admission_payload())
    _row(payload, "MS")["seed_disposition"]["disposition"] = DISPOSITION_CANDIDATE
    _reseal(payload)
    with pytest.raises(AuditError, match="MS"):
        validate_source_admission(payload, require_51=True)


def test_digest_mismatch_fails() -> None:
    payload = _mutated(build_source_admission_payload())
    payload["matrix_digest_sha256"] = "0" * 64
    with pytest.raises(AuditError, match="matrix_digest_sha256"):
        validate_source_admission(payload, require_51=True)


def test_cli_require_51_check_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--require-51", "--check"]) == 0
    captured = capsys.readouterr()
    assert "PASSED" in captured.out
    assert "jurisdictions=51" in captured.out


def test_cli_json_report_is_non_authorizing() -> None:
    # main writes JSON to stdout; capture via the return report path instead.
    report = audit_source_admission(build_source_admission_payload(), require_51=True)
    assert report["status"] == "passed"
    assert report["authorizing_for_publication"] is False
    assert report["require_51"] is True


def test_cli_missing_flags_fails() -> None:
    assert main([]) == 2
    assert main(["--check"]) == 2
    assert main(["--require-51"]) == 2


def test_repository_outputs_exist() -> None:
    root = _repo_root()
    assert (root / "data/legal/open_us_law/source_admission.schema.json").is_file()
    assert (root / "data/legal/open_us_law/source_admission.json").is_file()
    assert (root / "scripts/ops/legal_data/audit_open_us_law_sources.py").is_file()
