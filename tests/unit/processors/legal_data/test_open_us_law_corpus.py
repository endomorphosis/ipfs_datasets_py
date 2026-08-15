"""Unit tests for canonical Open US Law corpus materialization (OUL-024).

Acceptance: Canonical sections and structure-aware text chunks have
deterministic IDs and provenance; duplicate, contaminated, historical, PR,
federal, constitution, recovery, and unsupported rows are isolated in
explicit configurations or quarantine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_corpus import (
    AUTHORIZES_EXACT_51_PRODUCTION,
    AUTHORIZES_PUBLICATION,
    AUTHORIZES_RELEASE,
    CANONICAL_COUNT_FAMILIES,
    CURRENTNESS_DISCLAIMER,
    DEFAULT_CONFIGURATION,
    DEFAULT_MODEL_TOKEN_LIMIT,
    DEFAULT_RELEASE_POINT,
    EXACT_51_JURISDICTION_CODES,
    EXPECTED_JURISDICTION_COUNT,
    FIXTURE_SCHEMA_VERSION,
    GOAL_ID,
    MIN_USABLE_CHARS,
    PRODUCER,
    RELEASE_PROFILE,
    SCHEMA_VERSION,
    TASK_ID,
    TRANSFORMATION_VERSION,
    CanonicalChunk,
    CanonicalSection,
    ChunkIdentityError,
    DispositionError,
    Exact51AuthorizationError,
    IsolationReason,
    OpenUsLawCorpusError,
    OpenUsLawCorpusMaterializer,
    RowDisposition,
    assess_text_quality,
    assert_admitted_rows_complete,
    assert_chunks_have_deterministic_ids,
    assert_every_row_has_exactly_one_disposition,
    assert_non_default_isolated,
    assert_recovery_and_quarantine_excluded_from_canonical_counts,
    build_chunk_id,
    build_corpus_admission_report,
    build_default_jurisdiction_row,
    build_isolation_sample_rows,
    build_mixed_sample_rows,
    chunk_canonical_section,
    classify_source_row,
    default_corpus_admission_report_path,
    load_corpus_admission_report,
    looks_contaminated,
    materialize_open_us_law_corpus,
    parse_chunk_id,
    write_corpus_admission_report,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    LEGAL_ID_PREFIX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    NON_DEFAULT_CONFIGURATION_NAMES,
    ReleaseConfiguration,
    compute_text_hash,
    example_default_statute_payload,
    example_mixed_rows,
    validate_exact_51_gate,
)


REQUIRED_ISOLATION_REASONS = (
    IsolationReason.FEDERAL.value,
    IsolationReason.PUERTO_RICO.value,
    IsolationReason.CONSTITUTION.value,
    IsolationReason.HISTORICAL.value,
    IsolationReason.RECOVERY.value,
    IsolationReason.DUPLICATE.value,
    IsolationReason.CONTAMINATED.value,
    IsolationReason.UNSUPPORTED.value,
)


@pytest.fixture(scope="module")
def mixed_corpus():
    return materialize_open_us_law_corpus(build_mixed_sample_rows())


# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "open-us-law-corpus-v1"
    assert FIXTURE_SCHEMA_VERSION == "open-us-law-corpus-admission-v1"
    assert TASK_ID == "OUL-024"
    assert GOAL_ID == "OUL-G030"
    assert PRODUCER == "open_us_law_corpus.py"
    assert RELEASE_PROFILE == "open-us-law-sparse-graphrag/v1"
    assert DEFAULT_CONFIGURATION == "state_statutes_exact_51"
    assert DEFAULT_MODEL_TOKEN_LIMIT == 512
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert DEFAULT_MODEL_TOKEN_LIMIT != MAX_ROWS_PER_PHYSICAL_SHARD
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_RELEASE is False
    assert AUTHORIZES_EXACT_51_PRODUCTION is False
    assert "not a claim that the codified text is legally current" in CURRENTNESS_DISCLAIMER
    assert TRANSFORMATION_VERSION == "open-us-law-corpus-transform-v1"
    assert "corpus" in CANONICAL_COUNT_FAMILIES
    assert "bm25" in CANONICAL_COUNT_FAMILIES
    assert "vector" in CANONICAL_COUNT_FAMILIES
    assert "graph" in CANONICAL_COUNT_FAMILIES


def test_release_point_is_immutable_digest() -> None:
    assert len(DEFAULT_RELEASE_POINT) == 64
    assert DEFAULT_RELEASE_POINT == DEFAULT_RELEASE_POINT.lower()
    assert DEFAULT_RELEASE_POINT != "latest"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_classify_default_statute_is_admitted() -> None:
    row = example_default_statute_payload()
    classified = classify_source_row(row)
    assert classified.disposition is RowDisposition.ADMITTED
    assert classified.configuration is ReleaseConfiguration.STATE_STATUTES_EXACT_51
    assert classified.isolation_reason is IsolationReason.NONE
    assert classified.configuration.satisfies_exact_51_gate is True


@pytest.mark.parametrize(
    ("builder_index", "reason", "configuration"),
    [
        (0, IsolationReason.FEDERAL, ReleaseConfiguration.FEDERAL_USCODE),
        (1, IsolationReason.PUERTO_RICO, ReleaseConfiguration.PUERTO_RICO),
        (2, IsolationReason.CONSTITUTION, ReleaseConfiguration.CONSTITUTIONS),
        (3, IsolationReason.HISTORICAL, ReleaseConfiguration.HISTORICAL),
        (4, IsolationReason.RECOVERY, ReleaseConfiguration.RECOVERY),
        (6, IsolationReason.DUPLICATE, ReleaseConfiguration.QUARANTINE),
        (7, IsolationReason.CONTAMINATED, ReleaseConfiguration.QUARANTINE),
        (8, IsolationReason.UNSUPPORTED, ReleaseConfiguration.QUARANTINE),
    ],
)
def test_classify_isolates_non_default_families(builder_index, reason, configuration) -> None:
    row = build_isolation_sample_rows()[builder_index]
    classified = classify_source_row(row)
    assert classified.isolation_reason is reason
    assert classified.configuration is configuration
    assert classified.configuration.satisfies_exact_51_gate is False


def test_looks_contaminated_detects_placeholder_and_chrome() -> None:
    dirty = (
        "Skip to main content. Cookie banner. Lorem ipsum dolor sit amet. "
        "Subscribe to our newsletter. All rights reserved."
    )
    quality = assess_text_quality(dirty)
    assert quality.contaminated is True
    assert quality.placeholder_detected is True
    assert looks_contaminated({"text": dirty}) is True
    clean = "Oregon Revised Statutes section 1 shall apply to every person."
    assert assess_text_quality(clean).contaminated is False
    assert looks_contaminated({"text": clean}) is False
    assert looks_contaminated({"text": clean, "contaminated": True}) is True


def test_short_nav_only_text_is_contaminated() -> None:
    quality = assess_text_quality("Home > Statutes > Search")
    assert quality.contaminated is True
    assert quality.usable_chars < 64


# ---------------------------------------------------------------------------
# Materialization: exact-51 default + isolation
# ---------------------------------------------------------------------------


def test_mixed_sample_admits_exact_51_and_isolates_the_rest(mixed_corpus) -> None:
    assert len(mixed_corpus.admitted_sections) == EXPECTED_JURISDICTION_COUNT
    assert mixed_corpus.default_jurisdiction_codes() == EXACT_51_JURISDICTION_CODES
    assert mixed_corpus.default_jurisdiction_codes().count("DC") == 1
    assert "PR" not in mixed_corpus.default_jurisdiction_codes()
    assert "US" not in mixed_corpus.default_jurisdiction_codes()
    mapping = assert_every_row_has_exactly_one_disposition(mixed_corpus.ledger)
    assert len(mapping) == len(mixed_corpus.ledger)
    assert_admitted_rows_complete(mixed_corpus.admitted_sections)
    assert_chunks_have_deterministic_ids(mixed_corpus.admitted_chunks)
    assert_non_default_isolated(mixed_corpus)
    assert_recovery_and_quarantine_excluded_from_canonical_counts(mixed_corpus)


def test_every_required_isolation_reason_is_present(mixed_corpus) -> None:
    present = {entry.isolation_reason.value for entry in mixed_corpus.ledger}
    for reason in REQUIRED_ISOLATION_REASONS:
        assert reason in present
    counts = mixed_corpus.isolation_counts
    assert counts[IsolationReason.FEDERAL.value] >= 1
    assert counts[IsolationReason.PUERTO_RICO.value] >= 1
    assert counts[IsolationReason.CONSTITUTION.value] >= 1
    assert counts[IsolationReason.HISTORICAL.value] >= 1
    assert counts[IsolationReason.RECOVERY.value] >= 1
    assert counts[IsolationReason.DUPLICATE.value] >= 1
    assert counts[IsolationReason.CONTAMINATED.value] >= 1
    assert counts[IsolationReason.UNSUPPORTED.value] >= 1


def test_non_default_configurations_are_explicit(mixed_corpus) -> None:
    configs = mixed_corpus.configuration_counts
    for name in NON_DEFAULT_CONFIGURATION_NAMES:
        assert name in configs
    assert configs["federal_uscode"] >= 1
    assert configs["puerto_rico"] >= 1
    assert configs["constitutions"] >= 1
    assert configs["historical"] >= 1
    assert configs["recovery"] >= 1
    assert configs["quarantine"] >= 1
    assert configs[DEFAULT_CONFIGURATION] == EXPECTED_JURISDICTION_COUNT
    for section in mixed_corpus.isolated_sections:
        assert section.configuration in NON_DEFAULT_CONFIGURATION_NAMES
        assert section.to_dict()["satisfies_exact_51_gate"] is False
    for row in (*mixed_corpus.recovery_rows, *mixed_corpus.quarantine_rows):
        assert row.configuration in {"recovery", "quarantine"}
        assert row.to_dict()["satisfies_exact_51_gate"] is False


def test_exact_51_gate_ignores_isolated_rows(mixed_corpus) -> None:
    gate = validate_exact_51_gate(
        [section.to_dict() for section in mixed_corpus.admitted_sections],
        require_full_coverage=True,
    )
    assert gate["closed"] is True
    assert gate["default_row_count"] == EXPECTED_JURISDICTION_COUNT
    assert gate["non_default_satisfies_gate"] is False
    assert not gate["missing_jurisdictions"]
    assert not gate["extra_jurisdictions"]


# ---------------------------------------------------------------------------
# Deterministic IDs and provenance
# ---------------------------------------------------------------------------


def test_section_and_chunk_ids_are_deterministic() -> None:
    rows = build_mixed_sample_rows()
    first = materialize_open_us_law_corpus(rows)
    second = materialize_open_us_law_corpus(rows)
    assert [section.legal_id for section in first.admitted_sections] == [
        section.legal_id for section in second.admitted_sections
    ]
    assert [section.entry_cid for section in first.admitted_sections] == [
        section.entry_cid for section in second.admitted_sections
    ]
    assert [section.text_hash for section in first.admitted_sections] == [
        section.text_hash for section in second.admitted_sections
    ]
    assert [chunk.chunk_id for chunk in first.admitted_chunks] == [
        chunk.chunk_id for chunk in second.admitted_chunks
    ]
    assert [chunk.chunk_cid for chunk in first.admitted_chunks] == [
        chunk.chunk_cid for chunk in second.admitted_chunks
    ]


def test_admitted_sections_carry_required_identity_and_provenance(mixed_corpus) -> None:
    assert mixed_corpus.admitted_sections
    for section in mixed_corpus.admitted_sections:
        payload = section.to_dict()
        for field_name in (
            "jurisdiction_code",
            "hierarchy",
            "edition",
            "source_cid",
            "entry_cid",
            "text_hash",
            "legal_id",
            "acquisition_receipt_cid",
            "rights_receipt_cid",
            "observed_at",
            "transformation_version",
            "body_hash",
        ):
            assert payload[field_name] not in (None, "")
        assert payload["legal_id"].startswith(f"{LEGAL_ID_PREFIX}:")
        assert "row-" not in payload["legal_id"]
        assert payload["text_hash"] == compute_text_hash(payload["text"])
        assert payload["body_hash"] == payload["text_hash"]
        assert payload["configuration"] == DEFAULT_CONFIGURATION
        assert payload["satisfies_exact_51_gate"] is True
        assert payload["hierarchy"]["section"]
        assert payload["document_index"] >= 0
        CanonicalSection.from_mapping(payload)


def test_chunks_use_parent_legal_id_suffix_and_provenance(mixed_corpus) -> None:
    assert mixed_corpus.admitted_chunks
    by_parent: dict[str, list] = {}
    for chunk in mixed_corpus.admitted_chunks:
        parent, index = parse_chunk_id(chunk.chunk_id)
        assert parent == chunk.parent_legal_id
        assert index == chunk.chunk_index
        assert chunk.legal_id == chunk.chunk_id
        assert chunk.chunk_id == build_chunk_id(parent, index)
        assert chunk.source_cid
        assert chunk.entry_cid
        assert chunk.text_hash
        assert chunk.chunk_cid
        assert chunk.model_token_limit == DEFAULT_MODEL_TOKEN_LIMIT
        assert chunk.token_count <= DEFAULT_MODEL_TOKEN_LIMIT or chunk.limit_exempt
        assert chunk.configuration == DEFAULT_CONFIGURATION
        assert chunk.parent_path
        by_parent.setdefault(parent, []).append(chunk)
    oregon = next(
        section for section in mixed_corpus.admitted_sections if section.jurisdiction_code == "OR"
    )
    assert oregon.legal_id in by_parent
    assert by_parent[oregon.legal_id]


def test_structure_aware_chunking_splits_oversized_subsections() -> None:
    row = build_default_jurisdiction_row("OR", structured=True)
    row["text"] = (
        "Preamble that a person shall follow. "
        + " ".join(
            f"({chr(97 + index)}) "
            + "The licensee shall retain written records of every regulated act. " * 8
            for index in range(8)
        )
    )
    row.pop("text_hash", None)
    row.pop("entry_cid", None)
    materializer = OpenUsLawCorpusMaterializer(model_token_limit=40)
    corpus = materializer.materialize([row])
    assert len(corpus.admitted_sections) == 1
    assert len(corpus.admitted_chunks) >= 2
    parent = corpus.admitted_sections[0].legal_id
    for chunk in corpus.admitted_chunks:
        assert chunk.parent_legal_id == parent
        assert chunk.chunk_id.startswith(parent + "#chunk=")
        assert chunk.token_count <= 40 or chunk.limit_exempt
        CanonicalChunk.from_mapping(chunk.to_dict())
    rebuilt = chunk_canonical_section(
        corpus.admitted_sections[0],
        model_token_limit=40,
    )
    assert [chunk.chunk_id for chunk in rebuilt] == [
        chunk.chunk_id for chunk in corpus.admitted_chunks
    ]


def test_document_index_is_release_local_not_durable_identity(mixed_corpus) -> None:
    oregon = next(
        section for section in mixed_corpus.admitted_sections if section.jurisdiction_code == "OR"
    )
    assert oregon.document_index >= 0
    assert "row-" not in oregon.legal_id
    assert str(oregon.document_index) not in oregon.legal_id.split(":")[-1]


def test_positional_row_id_is_rejected() -> None:
    row = build_default_jurisdiction_row("WA")
    row["row_id"] = "row-12"
    with pytest.raises((DispositionError, OpenUsLawCorpusError)):
        materialize_open_us_law_corpus([row])


def test_incomplete_default_identity_is_quarantined_not_admitted() -> None:
    row = {
        "row_id": "broken-or",
        "jurisdiction_code": "OR",
        "code_family": "ors",
        "edition": "2024-official",
        "text": "A person shall keep records.",
    }
    corpus = materialize_open_us_law_corpus([row])
    assert corpus.admitted_sections == ()
    assert len(corpus.quarantine_rows) == 1
    assert corpus.quarantine_rows[0].isolation_reason == IsolationReason.UNSUPPORTED.value


# ---------------------------------------------------------------------------
# Isolation of each named family
# ---------------------------------------------------------------------------


def test_duplicate_legal_id_is_quarantined() -> None:
    first = build_default_jurisdiction_row("ME")
    second = dict(first)
    second["row_id"] = "duplicate-me-second"
    second.pop("duplicate", None)
    corpus = materialize_open_us_law_corpus([first, second])
    assert len(corpus.admitted_sections) == 1
    assert len(corpus.quarantine_rows) == 1
    assert corpus.quarantine_rows[0].isolation_reason == IsolationReason.DUPLICATE.value
    assert corpus.quarantine_rows[0].legal_id == corpus.admitted_sections[0].legal_id
    assert corpus.family_counts.corpus == 1
    assert corpus.family_counts.quarantine == 1


def test_contaminated_row_cannot_enter_default_or_search_counts() -> None:
    dirty = {
        "row_id": "dirty-ca",
        "jurisdiction_code": "CA",
        "code_family": "statutes",
        "edition": "2024-official",
        "hierarchy": {"title": "1", "section": "1"},
        "text": "Skip to main content. Lorem ipsum. Cookie banner. All rights reserved.",
    }
    clean = build_default_jurisdiction_row("CA")
    corpus = materialize_open_us_law_corpus([clean, dirty])
    assert len(corpus.admitted_sections) == 1
    assert corpus.admitted_sections[0].jurisdiction_code == "CA"
    contaminated = [
        row
        for row in corpus.quarantine_rows
        if row.isolation_reason == IsolationReason.CONTAMINATED.value
    ]
    assert contaminated
    assert corpus.family_counts.corpus == 1
    assert corpus.family_counts.quarantine == 1


def test_schema_example_mixed_rows_are_partitioned() -> None:
    rows = []
    for index, raw in enumerate(example_mixed_rows()):
        payload = dict(raw)
        payload.setdefault("row_id", f"schema-mix-{index:02d}")
        if payload.get("admission_status") == "admitted" and payload.get("text"):
            # Example payloads are short; keep them official-looking.
            if "shall" not in payload["text"]:
                payload["text"] = payload["text"] + " This section shall apply."
                payload["text_hash"] = compute_text_hash(payload["text"])
        rows.append(payload)
    # Recovery example is classified by admission_status.
    corpus = materialize_open_us_law_corpus(rows)
    configs = {entry.configuration.value for entry in corpus.ledger}
    assert DEFAULT_CONFIGURATION in configs
    assert "federal_uscode" in configs
    assert "puerto_rico" in configs
    assert "constitutions" in configs
    assert "historical" in configs
    assert "recovery" in configs
    assert "quarantine" in configs
    for section in corpus.admitted_sections:
        assert section.jurisdiction_code in EXACT_51_JURISDICTION_CODES


def test_recovery_and_quarantine_never_enter_family_counts(mixed_corpus) -> None:
    counts = mixed_corpus.family_counts.to_dict()
    admitted = len(mixed_corpus.admitted_sections)
    chunks = len(mixed_corpus.admitted_chunks)
    assert counts["corpus"] == admitted
    assert counts["chunks"] == chunks
    assert counts["bm25"] == chunks
    assert counts["vector"] == chunks
    assert counts["graph"] == chunks
    assert counts["recovery"] == len(mixed_corpus.recovery_rows) >= 1
    assert counts["quarantine"] == len(mixed_corpus.quarantine_rows) >= 1
    assert counts["corpus"] != admitted + counts["recovery"]
    assert counts["bm25"] != chunks + counts["quarantine"]


def test_duplicate_source_row_ids_fail_closed() -> None:
    row = build_default_jurisdiction_row("VT")
    with pytest.raises(DispositionError):
        materialize_open_us_law_corpus([row, dict(row)])


def test_materializer_rejects_token_ceiling_above_gte_limit() -> None:
    with pytest.raises(OpenUsLawCorpusError):
        OpenUsLawCorpusMaterializer(model_token_limit=4096)


def test_mutable_release_point_is_rejected() -> None:
    with pytest.raises(OpenUsLawCorpusError):
        OpenUsLawCorpusMaterializer(release_point="latest")


def test_non_mapping_rows_fail_closed() -> None:
    with pytest.raises(OpenUsLawCorpusError):
        materialize_open_us_law_corpus(["not-a-row"])  # type: ignore[list-item]


def test_authorizing_flags_cannot_be_set_on_materialized_corpus(mixed_corpus) -> None:
    with pytest.raises(Exact51AuthorizationError):
        Materialized = mixed_corpus.__class__
        Materialized(
            ledger=mixed_corpus.ledger,
            admitted_sections=mixed_corpus.admitted_sections,
            admitted_chunks=mixed_corpus.admitted_chunks,
            isolated_sections=mixed_corpus.isolated_sections,
            isolated_chunks=mixed_corpus.isolated_chunks,
            recovery_rows=mixed_corpus.recovery_rows,
            quarantine_rows=mixed_corpus.quarantine_rows,
            family_counts=mixed_corpus.family_counts,
            authorizing_for_publication=True,
        )


# ---------------------------------------------------------------------------
# Sealed admission report
# ---------------------------------------------------------------------------


def test_on_disk_admission_report_matches_builder(tmp_path: Path) -> None:
    built = build_corpus_admission_report()
    assert built["task_id"] == TASK_ID
    assert built["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert built["authorizing_for_publication"] is False
    assert built["authorizing_for_release"] is False
    assert built["acceptance"]["canonical_sections_have_deterministic_ids"] is True
    assert built["acceptance"]["canonical_chunks_have_deterministic_ids"] is True
    assert built["acceptance"][
        "duplicate_contaminated_historical_pr_federal_constitution_recovery_unsupported_isolated"
    ]
    assert built["checks"]["deterministic_ids_across_replay"] is True
    assert built["checks"]["default_jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert built["checks"]["model_token_ceiling"] == 512
    assert built["checks"]["physical_shard_bound_not_used_as_token_ceiling"] is True
    assert built["demo"]["admitted_jurisdictions"] == list(EXACT_51_JURISDICTION_CODES)
    isolated_reasons = {
        item["isolation_reason"] for item in built["demo"]["isolation_examples"]
    }
    for reason in REQUIRED_ISOLATION_REASONS:
        assert reason in isolated_reasons
    assert built["report_digest_sha256"]
    assert built["depends_on"] == ["OUL-001", "OUL-005", "OUL-023"]
    assert built["identity"]["chunk_id_pattern"] == "{parent_legal_id}#chunk=NNNN"
    assert built["demo"]["structured_chunks"]

    on_disk_path = default_corpus_admission_report_path()
    if on_disk_path.is_file():
        loaded = load_corpus_admission_report(on_disk_path)
        assert loaded["task_id"] == built["task_id"]
        assert loaded["schema_version"] == built["schema_version"]
        assert loaded["acceptance"] == built["acceptance"]
        assert loaded["checks"]["default_jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
        assert loaded["authorizing_for_publication"] is False
        assert loaded["report_digest_sha256"] == built["report_digest_sha256"]

    written = write_corpus_admission_report(tmp_path / "corpus_admission.json")
    rerun = json.loads(written.read_text(encoding="utf-8"))
    assert rerun["report_digest_sha256"] == built["report_digest_sha256"]
    assert rerun["family_counts"] == built["family_counts"]


def test_load_report_rejects_wrong_schema(tmp_path: Path) -> None:
    target = tmp_path / "bad.json"
    target.write_text(json.dumps({"schema_version": "nope", "task_id": TASK_ID}), encoding="utf-8")
    from ipfs_datasets_py.processors.legal_data.open_us_law_corpus import CorpusFixtureError

    with pytest.raises(CorpusFixtureError):
        load_corpus_admission_report(target)


def test_min_usable_chars_constant_is_below_fixture_statutes() -> None:
    row = build_default_jurisdiction_row("WY")
    assert len(row["text"]) >= MIN_USABLE_CHARS
    assert assess_text_quality(row["text"]).contaminated is False


def test_chunk_id_round_trip() -> None:
    parent = "oul:statute:OR:ors:1:1;edition=2024-official"
    chunk_id = build_chunk_id(parent, 3)
    assert chunk_id.endswith("#chunk=0003")
    assert parse_chunk_id(chunk_id) == (parent, 3)
    with pytest.raises(ChunkIdentityError):
        parse_chunk_id("not-a-chunk")
    with pytest.raises((ChunkIdentityError, OpenUsLawCorpusError)):
        build_chunk_id("row-9", 0)
