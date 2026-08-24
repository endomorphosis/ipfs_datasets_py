"""Unit tests for structure-aware state statute chunking (LCR-025).

Acceptance:

* Text reconstruction.
* Legal-boundary preservation.
* Huge-section behavior is bounded.
* Deterministic CIDs.
* Per-jurisdiction fixtures pass.
* 4096 rows is never confused with token length.
* Tests are hermetic: no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    build_explicit_statute_row,
    code_family_for,
)
from ipfs_datasets_py.processors.legal_data.state_laws_chunker import (
    DEFAULT_MAX_CHUNKS_PER_SECTION,
    DEFAULT_TOKENIZER_ID,
    FIXTURE_SCHEMA_VERSION,
    GOAL_ID,
    PHYSICAL_ROW_LIMIT,
    PRODUCER,
    SCHEMA_VERSION,
    TASK_ID,
    ChunkBoundaryFixtureError,
    ChunkerConfigError,
    LegalTextChunk,
    SplitMode,
    StateLawsChunker,
    StateLawsChunkerError,
    assert_chunks_within_limit,
    assert_exact_reconstruction,
    assert_legal_boundaries_preserved,
    boundary_fingerprint,
    build_default_chunk_boundary_fixture_payload,
    chunk_corpus_row,
    chunk_state_statute,
    count_tokens,
    default_chunk_boundary_fixture_path,
    expand_case_text,
    expand_per_jurisdiction_cases,
    find_structural_markers,
    load_chunk_boundary_fixture_payload,
    parse_chunk_id,
    reconstruct_text,
    run_fixture_case,
    segment_structural_units,
    tokenize,
    validate_model_token_limit,
)
from ipfs_datasets_py.processors.legal_data.state_laws_identity import (
    build_legal_id,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "state_laws_chunk_boundaries.json"
)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return load_chunk_boundary_fixture_payload(_FIXTURE_PATH)


@pytest.fixture(scope="module")
def fixture_cases(fixture_payload: dict) -> list[dict]:
    return list(fixture_payload["cases"])


@pytest.fixture(scope="module")
def per_jurisdiction_cases(fixture_payload: dict) -> list[dict]:
    return expand_per_jurisdiction_cases(fixture_payload)


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_chunk_boundary_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_chunk_boundary_fixture_path().name == "state_laws_chunk_boundaries.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 64_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["physical_row_limit"] == PHYSICAL_ROW_LIMIT
    assert payload["tokenizer_id"] == DEFAULT_TOKENIZER_ID
    assert payload["task_id"] == TASK_ID
    assert isinstance(payload["cases"], list)
    assert len(payload["cases"]) >= 5
    assert len(payload["jurisdictions"]) == EXPECTED_JURISDICTION_COUNT
    assert tuple(payload["jurisdictions"]) == CANONICAL_JURISDICTION_ORDER
    for case in payload["cases"]:
        assert "case_id" in case
        assert "expect" in case
        assert "chunks" not in case
        assert "jurisdiction" in case


def test_default_payload_matches_on_disk_recipe():
    built = build_default_chunk_boundary_fixture_payload()
    on_disk = load_chunk_boundary_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["physical_row_limit"] == on_disk["physical_row_limit"]
    built_ids = [c["case_id"] for c in built["cases"]]
    disk_ids = [c["case_id"] for c in on_disk["cases"]]
    assert built_ids == disk_ids
    assert built["jurisdictions"] == on_disk["jurisdictions"]


def test_malformed_fixture_rejected(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "nope", "cases": []}), encoding="utf-8")
    with pytest.raises(ChunkBoundaryFixtureError):
        load_chunk_boundary_fixture_payload(bad)


def test_fixture_rejects_wrong_jurisdiction_set(tmp_path: Path):
    payload = build_default_chunk_boundary_fixture_payload()
    payload["jurisdictions"] = list(CANONICAL_JURISDICTION_ORDER[:-1])
    bad = tmp_path / "short.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ChunkBoundaryFixtureError):
        load_chunk_boundary_fixture_payload(bad)


# ---------------------------------------------------------------------------
# Config: model token limit is explicit; 4096 row bound is not reused
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable():
    assert SCHEMA_VERSION == "state-laws-chunker-v1"
    assert FIXTURE_SCHEMA_VERSION == "state-laws-chunk-boundaries-v1"
    assert TASK_ID == "LCR-025"
    assert GOAL_ID == "LCR-G030"
    assert PRODUCER == "state_laws_chunker.py"
    assert PHYSICAL_ROW_LIMIT == 4096
    assert DEFAULT_TOKENIZER_ID == "state-laws-whitespace-v1"


def test_model_token_limit_is_required():
    with pytest.raises(ChunkerConfigError) as excinfo:
        validate_model_token_limit(None)
    msg = str(excinfo.value).lower()
    assert "model_token_limit" in msg
    assert "required" in msg
    assert "4096" in msg or "row" in msg


def test_model_token_limit_rejects_non_positive():
    with pytest.raises(ChunkerConfigError):
        validate_model_token_limit(0)
    with pytest.raises(ChunkerConfigError):
        validate_model_token_limit(-5)
    with pytest.raises(ChunkerConfigError):
        validate_model_token_limit("abc")


def test_physical_row_limit_is_not_implicit_token_default():
    assert PHYSICAL_ROW_LIMIT == 4096
    chunker = StateLawsChunker()
    with pytest.raises(ChunkerConfigError) as excinfo:
        chunker.chunk_statute(
            "Short statutory text about licensed activity.",
            model_token_limit=None,  # type: ignore[arg-type]
            jurisdiction="OR",
            section="163.005",
        )
    assert "4096" in str(excinfo.value) or "row" in str(excinfo.value).lower()


def test_explicit_4096_token_limit_is_caller_opt_in_not_row_bound():
    result = chunk_state_statute(
        "A short licensed provision shall apply.",
        model_token_limit=4096,
        jurisdiction="OR",
        section="1.01",
        overlap_tokens=0,
    )
    assert result.model_token_limit == 4096
    assert result.model_token_limit == PHYSICAL_ROW_LIMIT
    assert len(result.chunks) == 1
    assert result.chunks[0].token_count != PHYSICAL_ROW_LIMIT


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------


def test_tokenize_is_deterministic_and_offset_aligned():
    text = "Section 163.005 provides that (a) person means a human being."
    tokens = tokenize(text)
    assert tokens
    for tok in tokens:
        assert text[tok.char_start : tok.char_end] == tok.text
    assert count_tokens(text) == len(tokens)
    assert tokenize(text) == tokenize(text)


def test_find_structural_markers_detects_hierarchy_and_subsections():
    text = (
        "PENAL CODE\n"
        "TITLE 1. CRIMES\n"
        "CHAPTER 2. PERSONS\n"
        "SECTION 26. Capacity\n"
        "Preamble text.\n"
        "(a) First.\n"
        "(1) Nested.\n"
        "(b) Second."
    )
    markers = find_structural_markers(text)
    kinds = [m[3].value for m in markers]
    tokens = [m[2] for m in markers]
    assert "code" in kinds
    assert "title" in kinds
    assert "chapter" in kinds
    assert "section" in kinds
    assert "penal-code" in tokens
    assert "26" in tokens
    labels = [f"({m[2]})" for m in markers if m[3].value in {"subsection", "paragraph"}]
    assert "(a)" in labels
    assert "(1)" in labels
    assert "(b)" in labels


def test_segment_structural_units_cover_full_text():
    text = "Intro.\n(a) Alpha body.\n(b) Beta body."
    units = segment_structural_units(
        text, base_path=("jurisdiction:OR", "code:oregon-revised-statutes", "section:1")
    )
    assert units
    rebuilt = "".join(u.text for u in units)
    assert rebuilt == text
    assert units[0].char_start == 0
    assert units[-1].char_end == len(text)


# ---------------------------------------------------------------------------
# Acceptance: no non-exempt chunk exceeds model limit
# ---------------------------------------------------------------------------


def test_no_non_exempt_chunk_exceeds_model_limit(fixture_cases):
    for case in fixture_cases:
        result = run_fixture_case(case)
        limit = int(case["model_token_limit"])
        assert_chunks_within_limit(result.chunks, limit)
        for chunk in result.chunks:
            if chunk.limit_exempt:
                continue
            assert count_tokens(chunk.text) <= limit
            assert chunk.token_count <= limit
            assert chunk.model_token_limit == limit


def test_assert_chunks_within_limit_fails_on_violation():
    result = chunk_state_statute(
        "alpha beta gamma delta epsilon zeta eta theta",
        model_token_limit=100,
        jurisdiction="TX",
        section="1",
        overlap_tokens=0,
    )
    bad = result.chunks[0].to_dict()
    bad["text"] = "word " * 200
    bad["token_count"] = count_tokens(bad["text"])
    bad["limit_exempt"] = False
    with pytest.raises(StateLawsChunkerError):
        assert_chunks_within_limit([bad], model_token_limit=10)


# ---------------------------------------------------------------------------
# Acceptance: exact text reconstruction
# ---------------------------------------------------------------------------


def test_exact_text_reconstruction_on_fixture_cases(fixture_cases):
    for case in fixture_cases:
        expect = case.get("expect") or {}
        if not expect.get("exact_reconstruction", True):
            if expect.get("bounded"):
                result = run_fixture_case(case)
                rebuilt = reconstruct_text(result.chunks)
                if not result.truncated:
                    assert rebuilt == result.source_text
                else:
                    assert result.source_text.startswith(rebuilt) or rebuilt == result.source_text[
                        : len(rebuilt)
                    ]
                continue
        result = run_fixture_case(case)
        if result.truncated:
            continue
        assert_exact_reconstruction(result.source_text, result.chunks)
        assert reconstruct_text(result.chunks) == result.source_text


def test_exact_reconstruction_with_overlap():
    text = (
        "(a) The Secretary shall prescribe regulations. "
        "(b) Such regulations shall include standards for safety. "
        "(c) The standards shall be updated periodically as needed."
    )
    result = chunk_state_statute(
        text,
        model_token_limit=12,
        jurisdiction="CA",
        code_family="california-codes",
        title="1",
        chapter="1",
        section="26",
        overlap_tokens=3,
    )
    assert len(result.chunks) >= 2
    assert any(c.overlap_token_count > 0 for c in result.chunks[1:])
    assert_exact_reconstruction(result.source_text, result.chunks)
    cursor = 0
    for chunk in sorted(result.chunks, key=lambda c: c.char_start):
        assert chunk.char_start == cursor
        assert chunk.exclusive_text == result.source_text[chunk.char_start : chunk.char_end]
        cursor = chunk.char_end
    assert cursor == len(result.source_text)


def test_empty_text_yields_no_chunks():
    result = chunk_state_statute(
        "",
        model_token_limit=64,
        jurisdiction="OR",
        section="1",
    )
    assert result.chunks == ()
    assert reconstruct_text(result.chunks) == ""


# ---------------------------------------------------------------------------
# Acceptance: legal-boundary preservation
# ---------------------------------------------------------------------------


def test_legal_boundaries_preserved_on_fixture_cases(fixture_cases):
    for case in fixture_cases:
        result = run_fixture_case(case)
        assert_legal_boundaries_preserved(result.source_text, result.chunks)


def test_legal_boundaries_split_on_subsections_not_inside_markers():
    text = (
        "TITLE 5. PUBLIC OFFICERS\n"
        "CHAPTER 1. RECORDS\n"
        "SECTION 552. Public information\n"
        "(a) Each agency shall separately state and currently publish in the "
        "register for the guidance of the public the descriptions of its "
        "organization and methods of operation including field offices.\n"
        "(b) This section does not apply to matters that are specifically "
        "authorized to be kept secret in the interest of national defense.\n"
        "(c) Any reasonably segregable portion of a record shall be provided "
        "after deletion of the portions which are exempt under this subsection."
    )
    result = chunk_state_statute(
        text,
        model_token_limit=20,
        jurisdiction="CA",
        code_family="california-codes",
        title="5",
        chapter="1",
        section="552",
        overlap_tokens=0,
    )
    assert len(result.chunks) >= 2
    assert_legal_boundaries_preserved(result.source_text, result.chunks)
    assert_exact_reconstruction(result.source_text, result.chunks)
    marker_starts = {0} | {m[0] for m in find_structural_markers(result.source_text)}
    for chunk in result.chunks:
        if chunk.split_mode in {SplitMode.STRUCTURE.value, SplitMode.WHOLE.value}:
            assert chunk.char_start in marker_starts


# ---------------------------------------------------------------------------
# Acceptance: boundaries are deterministic / CIDs
# ---------------------------------------------------------------------------


def test_boundaries_are_deterministic(fixture_cases):
    for case in fixture_cases:
        first = boundary_fingerprint(run_fixture_case(case))
        second = boundary_fingerprint(run_fixture_case(case))
        assert first == second
        assert [row["chunk_cid"] for row in first] == [row["chunk_cid"] for row in second]
        assert [row["chunk_id"] for row in first] == [row["chunk_id"] for row in second]


def test_deterministic_case_fingerprint_stable(fixture_cases):
    case = next(c for c in fixture_cases if c["case_id"] == "deterministic-boundaries")
    fp1 = boundary_fingerprint(run_fixture_case(case))
    fp2 = boundary_fingerprint(run_fixture_case(case))
    assert fp1 == fp2
    assert fp1
    expected_parent = build_legal_id(
        jurisdiction="DC",
        code_family="dc-official-code",
        title="22",
        chapter="4",
        section="22-404",
    )
    for row in fp1:
        assert row["chunk_id"].startswith(f"{expected_parent}#chunk=")
        assert row["chunk_cid"]
        parent, index = parse_chunk_id(row["chunk_id"])
        assert parent == expected_parent
        assert index == row["chunk_index"]


def test_chunk_ids_are_sequential_under_parent():
    text = "(a) One. (b) Two. (c) Three. (d) Four. (e) Five. (f) Six."
    result = chunk_state_statute(
        text,
        model_token_limit=8,
        jurisdiction="OR",
        code_family="oregon-revised-statutes",
        title="16",
        chapter="163",
        section="163.005",
        overlap_tokens=0,
    )
    assert result.parent_legal_id.startswith("state:OR:oregon-revised-statutes:")
    for index, chunk in enumerate(result.chunks):
        assert chunk.chunk_index == index
        assert chunk.chunk_id == f"{result.parent_legal_id}#chunk={index:04d}"
        assert chunk.parent_legal_id == result.parent_legal_id


# ---------------------------------------------------------------------------
# Acceptance: huge-section behavior is bounded
# ---------------------------------------------------------------------------


def test_huge_section_behavior_is_bounded(fixture_cases):
    case = next(c for c in fixture_cases if c["case_id"] == "huge-section-bounded")
    result = run_fixture_case(case)
    max_chunks = int(case.get("max_chunks_per_section") or case["expect"]["max_chunks"])
    assert len(result.chunks) <= max_chunks
    assert len(result.chunks) <= case["expect"]["max_chunks"]
    assert_chunks_within_limit(result.chunks, int(case["model_token_limit"]))
    assert result.source_token_count > int(case["model_token_limit"]) * max_chunks
    assert result.max_chunks_per_section == max_chunks


def test_max_chunks_per_section_caps_output():
    text = " ".join(f"token{i}" for i in range(500))
    result = chunk_state_statute(
        text,
        model_token_limit=10,
        jurisdiction="FL",
        section="1",
        overlap_tokens=0,
        max_chunks_per_section=5,
    )
    assert len(result.chunks) <= 5
    assert result.truncated is True or len(result.chunks) <= 5


# ---------------------------------------------------------------------------
# Structure-aware splitting and parent paths
# ---------------------------------------------------------------------------


def test_structure_case_splits_on_subsections(fixture_cases):
    case = next(c for c in fixture_cases if c["case_id"] == "subsection-structure")
    result = run_fixture_case(case)
    assert len(result.chunks) >= case["expect"]["min_chunks"]
    modes = {c.split_mode for c in result.chunks}
    assert modes & {
        SplitMode.STRUCTURE.value,
        SplitMode.WHOLE.value,
        SplitMode.SENTENCE.value,
        SplitMode.HARD.value,
    }
    for chunk in result.chunks:
        assert chunk.parent_path[0] == "jurisdiction:CA"
        assert chunk.parent_path[1] == "code:california-codes"
        assert "section:26" in chunk.parent_path


def test_hierarchy_case_records_code_title_chapter_section(fixture_cases):
    case = next(
        c for c in fixture_cases if c["case_id"] == "code-title-chapter-section-subsection"
    )
    result = run_fixture_case(case)
    assert len(result.chunks) >= case["expect"]["min_chunks"]
    assert_exact_reconstruction(result.source_text, result.chunks)
    joined = ["/" + "/".join(c.parent_path) for c in result.chunks]
    assert any("code:penal-code" in p or "code:texas-statutes" in p for p in joined)
    assert any("title:" in p for p in joined)
    assert any("chapter:" in p for p in joined)
    assert any("section:" in p for p in joined)


def test_nested_paragraph_parent_paths(fixture_cases):
    case = next(c for c in fixture_cases if c["case_id"] == "nested-paragraph-path")
    result = run_fixture_case(case)
    assert result.chunks
    assert all(chunk.parent_path for chunk in result.chunks)
    joined_paths = ["/" + "/".join(c.parent_path) for c in result.chunks]
    assert any("section:5-1" in p for p in joined_paths)


def test_hard_split_case_produces_multiple_chunks(fixture_cases):
    case = next(c for c in fixture_cases if c["case_id"] == "hard-split-no-markers")
    result = run_fixture_case(case)
    assert len(result.chunks) >= case["expect"]["min_chunks"]
    assert all(not c.limit_exempt for c in result.chunks)
    assert_exact_reconstruction(result.source_text, result.chunks)


def test_short_section_is_single_whole_chunk(fixture_cases):
    case = next(c for c in fixture_cases if c["case_id"] == "short-whole-section")
    result = run_fixture_case(case)
    assert len(result.chunks) == 1
    assert result.chunks[0].split_mode == SplitMode.WHOLE.value
    assert result.chunks[0].jurisdiction == "OR"
    assert result.chunks[0].section == "163.005"
    assert result.chunks[0].heading


# ---------------------------------------------------------------------------
# Per-jurisdiction fixtures
# ---------------------------------------------------------------------------


def test_per_jurisdiction_fixtures_pass(per_jurisdiction_cases):
    assert len(per_jurisdiction_cases) == EXPECTED_JURISDICTION_COUNT
    codes = [case["jurisdiction"] for case in per_jurisdiction_cases]
    assert tuple(codes) == CANONICAL_JURISDICTION_ORDER
    for case in per_jurisdiction_cases:
        result = run_fixture_case(case)
        assert result.jurisdiction == case["jurisdiction"]
        assert result.schema_version == SCHEMA_VERSION
        assert result.model_token_limit == int(case["model_token_limit"])
        assert result.chunks
        assert_exact_reconstruction(result.source_text, result.chunks)
        assert_chunks_within_limit(result.chunks, result.model_token_limit)
        assert_legal_boundaries_preserved(result.source_text, result.chunks)
        first = boundary_fingerprint(result)
        second = boundary_fingerprint(run_fixture_case(case))
        assert first == second
        for row in first:
            assert row["chunk_cid"]
            assert row["chunk_id"].startswith(f"state:{case['jurisdiction']}:")


def test_per_jurisdiction_code_family_comes_from_catalog(per_jurisdiction_cases):
    sample = [c for c in per_jurisdiction_cases if c["jurisdiction"] in {"CA", "NY", "TX", "DC"}]
    assert sample
    for case in sample:
        result = run_fixture_case(case)
        assert result.code_family == code_family_for(case["jurisdiction"])


# ---------------------------------------------------------------------------
# Corpus row integration (import corpus/identity, do not rewrite adapters)
# ---------------------------------------------------------------------------


def test_chunk_corpus_row_uses_durable_identity():
    row = build_explicit_statute_row(
        "WA",
        "9A.36.011",
        title="9A",
        chapter="36",
        heading="Assault in the first degree",
    )
    result = chunk_corpus_row(row, model_token_limit=64, overlap_tokens=0)
    assert result.jurisdiction == "WA"
    assert result.legal_id.startswith("state:WA:")
    assert result.chunks
    assert_exact_reconstruction(result.source_text, result.chunks)
    assert result.chunks[0].parent_legal_id == result.parent_legal_id


# ---------------------------------------------------------------------------
# Module helpers / serialization
# ---------------------------------------------------------------------------


def test_chunk_to_dict_round_trip():
    result = chunk_state_statute(
        "(a) First clause. (b) Second clause with more words here.",
        model_token_limit=16,
        jurisdiction="MN",
        section="101",
        overlap_tokens=2,
    )
    assert result.chunks
    payload = result.chunks[0].to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION
    restored = LegalTextChunk.from_mapping(payload)
    assert restored.chunk_id == result.chunks[0].chunk_id
    assert restored.chunk_cid == result.chunks[0].chunk_cid
    assert restored.exclusive_text == result.chunks[0].exclusive_text


def test_chunker_class_defaults():
    chunker = StateLawsChunker()
    assert chunker.max_chunks_per_section == DEFAULT_MAX_CHUNKS_PER_SECTION
    assert chunker.tokenizer_id == DEFAULT_TOKENIZER_ID
    result = chunker.chunk_statute(
        "A short provision.",
        model_token_limit=32,
        jurisdiction="ME",
        section="2",
    )
    assert len(result.chunks) == 1


def test_expand_case_text_recipe():
    text = expand_case_text(
        {
            "case_id": "x",
            "text_recipe": {
                "kind": "repeat_sentence",
                "sentence": "hello ",
                "repeat": 3,
            },
        }
    )
    assert text == "hello hello hello "


def test_expand_corpus_fixture_statute_recipe():
    text = expand_case_text(
        {
            "case_id": "y",
            "jurisdiction": "OR",
            "section": "1.01",
            "text_recipe": {
                "kind": "corpus_fixture_statute",
                "jurisdiction": "OR",
                "section": "1.01",
                "min_chars": 80,
            },
        }
    )
    assert "OR" in text
    assert "shall" in text.lower()
    assert len(text) >= 80


def test_all_fixture_cases_execute_cleanly(fixture_cases):
    for case in fixture_cases:
        result = run_fixture_case(case)
        assert result.model_token_limit == int(case["model_token_limit"])
        assert result.schema_version == SCHEMA_VERSION
        assert result.tokenizer_id
        assert_chunks_within_limit(result.chunks, result.model_token_limit)
