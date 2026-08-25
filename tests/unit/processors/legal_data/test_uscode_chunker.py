"""Unit tests for structure-aware U.S. Code text chunking (USCIR-007).

Acceptance:

* No non-exempt chunk exceeds the selected model limit.
* Exact text reconstruction is tested.
* Boundaries are deterministic.
* Huge-section behavior is bounded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_chunker import (
    DEFAULT_MAX_CHUNKS_PER_SECTION,
    DEFAULT_TOKENIZER_ID,
    FIXTURE_SCHEMA_VERSION,
    PHYSICAL_ROW_LIMIT,
    SCHEMA_VERSION,
    ChunkBoundaryFixtureError,
    ChunkerConfigError,
    SplitMode,
    UscodeChunker,
    UscodeChunkerError,
    assert_chunks_within_limit,
    assert_exact_reconstruction,
    boundary_fingerprint,
    build_default_chunk_boundary_fixture_payload,
    chunk_uscode_section,
    count_tokens,
    default_chunk_boundary_fixture_path,
    expand_case_text,
    find_structural_markers,
    load_chunk_boundary_fixture_payload,
    reconstruct_text,
    run_fixture_case,
    segment_structural_units,
    tokenize,
    validate_model_token_limit,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "uscode_chunk_boundaries.json"
)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return load_chunk_boundary_fixture_payload(_FIXTURE_PATH)


@pytest.fixture(scope="module")
def fixture_cases(fixture_payload: dict) -> list[dict]:
    return list(fixture_payload["cases"])


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_chunk_boundary_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_chunk_boundary_fixture_path().name == "uscode_chunk_boundaries.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 64_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["physical_row_limit"] == PHYSICAL_ROW_LIMIT
    assert payload["tokenizer_id"] == DEFAULT_TOKENIZER_ID
    assert isinstance(payload["cases"], list)
    assert len(payload["cases"]) >= 5
    # Recipe form: cases may use text_recipe; no bulk per-chunk golden dumps.
    for case in payload["cases"]:
        assert "case_id" in case
        assert "expect" in case
        assert "chunks" not in case


def test_default_payload_matches_on_disk_recipe():
    built = build_default_chunk_boundary_fixture_payload()
    on_disk = load_chunk_boundary_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["physical_row_limit"] == on_disk["physical_row_limit"]
    built_ids = [c["case_id"] for c in built["cases"]]
    disk_ids = [c["case_id"] for c in on_disk["cases"]]
    assert built_ids == disk_ids


def test_malformed_fixture_rejected(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "nope", "cases": []}), encoding="utf-8")
    with pytest.raises(ChunkBoundaryFixtureError):
        load_chunk_boundary_fixture_payload(bad)


# ---------------------------------------------------------------------------
# Config: model token limit is explicit; 4096 row bound is not reused
# ---------------------------------------------------------------------------


def test_model_token_limit_is_required():
    with pytest.raises(ChunkerConfigError) as excinfo:
        validate_model_token_limit(None)
    msg = str(excinfo.value).lower()
    assert "model_token_limit" in msg
    assert "required" in msg


def test_model_token_limit_rejects_non_positive():
    with pytest.raises(ChunkerConfigError):
        validate_model_token_limit(0)
    with pytest.raises(ChunkerConfigError):
        validate_model_token_limit(-5)
    with pytest.raises(ChunkerConfigError):
        validate_model_token_limit("abc")


def test_physical_row_limit_is_not_implicit_token_default():
    # Callers may choose 4096 as a model limit, but it is never injected.
    assert PHYSICAL_ROW_LIMIT == 4096
    chunker = UscodeChunker()
    with pytest.raises(ChunkerConfigError):
        chunker.chunk_section(
            "Short statutory text about patents.",
            model_token_limit=None,  # type: ignore[arg-type]
            title="35",
            section="101",
        )


def test_schema_version_stable():
    assert SCHEMA_VERSION.startswith("uscode-chunker")
    assert FIXTURE_SCHEMA_VERSION.startswith("uscode-chunk-boundaries")


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------


def test_tokenize_is_deterministic_and_offset_aligned():
    text = "Section 101 provides that (a) inventions are patentable."
    tokens = tokenize(text)
    assert tokens
    for tok in tokens:
        assert text[tok.char_start : tok.char_end] == tok.text
    assert count_tokens(text) == len(tokens)
    assert tokenize(text) == tokenize(text)


def test_find_structural_markers_detects_subsections():
    text = "Preamble text.\n(a) First.\n(1) Nested.\n(b) Second."
    markers = find_structural_markers(text)
    labels = [f"({m[2]})" for m in markers]
    assert "(a)" in labels
    assert "(1)" in labels
    assert "(b)" in labels


def test_segment_structural_units_cover_full_text():
    text = "Intro.\n(a) Alpha body.\n(b) Beta body."
    units = segment_structural_units(text, base_path=("title:5", "section:1"))
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
    result = chunk_uscode_section(
        "alpha beta gamma delta epsilon zeta eta theta",
        model_token_limit=100,
        title="1",
        section="1",
        overlap_tokens=0,
    )
    # Forge an oversize non-exempt chunk.
    bad = result.chunks[0].to_dict()
    bad["text"] = "word " * 200
    bad["token_count"] = count_tokens(bad["text"])
    bad["limit_exempt"] = False
    with pytest.raises(UscodeChunkerError):
        assert_chunks_within_limit([bad], model_token_limit=10)


# ---------------------------------------------------------------------------
# Acceptance: exact text reconstruction
# ---------------------------------------------------------------------------


def test_exact_text_reconstruction_on_fixture_cases(fixture_cases):
    for case in fixture_cases:
        expect = case.get("expect") or {}
        if not expect.get("exact_reconstruction", True):
            # Huge bounded case may truncate; still reconstruct covered prefix.
            if expect.get("bounded"):
                result = run_fixture_case(case)
                rebuilt = reconstruct_text(result.chunks)
                if not result.truncated:
                    assert rebuilt == result.source_text
                else:
                    assert result.source_text.startswith(rebuilt) or rebuilt == result.source_text[: len(rebuilt)]
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
    result = chunk_uscode_section(
        text,
        model_token_limit=12,
        title="49",
        section="30111",
        overlap_tokens=3,
    )
    assert len(result.chunks) >= 2
    assert any(c.overlap_token_count > 0 for c in result.chunks[1:])
    assert_exact_reconstruction(result.source_text, result.chunks)
    # Exclusive spans are contiguous and non-overlapping.
    cursor = 0
    for chunk in sorted(result.chunks, key=lambda c: c.char_start):
        assert chunk.char_start == cursor
        assert chunk.exclusive_text == result.source_text[chunk.char_start : chunk.char_end]
        cursor = chunk.char_end
    assert cursor == len(result.source_text)


def test_empty_text_yields_no_chunks():
    result = chunk_uscode_section(
        "",
        model_token_limit=64,
        title="1",
        section="1",
    )
    assert result.chunks == ()
    assert reconstruct_text(result.chunks) == ""


# ---------------------------------------------------------------------------
# Acceptance: boundaries are deterministic
# ---------------------------------------------------------------------------


def test_boundaries_are_deterministic(fixture_cases):
    for case in fixture_cases:
        first = boundary_fingerprint(run_fixture_case(case))
        second = boundary_fingerprint(run_fixture_case(case))
        assert first == second
        # CIDs and chunk ids stable across runs.
        assert [row["chunk_cid"] for row in first] == [row["chunk_cid"] for row in second]
        assert [row["chunk_id"] for row in first] == [row["chunk_id"] for row in second]


def test_deterministic_case_fingerprint_stable(fixture_cases):
    case = next(c for c in fixture_cases if c["case_id"] == "deterministic-boundaries")
    fp1 = boundary_fingerprint(run_fixture_case(case))
    fp2 = boundary_fingerprint(run_fixture_case(case))
    assert fp1 == fp2
    assert fp1
    for row in fp1:
        assert row["chunk_id"].startswith("usc:us:42:1983#chunk=")
        assert row["chunk_cid"]


def test_chunk_ids_are_sequential_under_parent():
    text = "(a) One. (b) Two. (c) Three. (d) Four. (e) Five. (f) Six."
    result = chunk_uscode_section(
        text,
        model_token_limit=8,
        title="5",
        section="552",
        overlap_tokens=0,
    )
    assert result.parent_legal_id == "usc:us:5:552"
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
    # Source is intentionally huge relative to the budget.
    assert result.source_token_count > int(case["model_token_limit"]) * max_chunks
    assert result.max_chunks_per_section == max_chunks


def test_max_chunks_per_section_caps_output():
    # Long marker-free text forces many hard windows.
    text = " ".join(f"token{i}" for i in range(500))
    result = chunk_uscode_section(
        text,
        model_token_limit=10,
        title="18",
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
    # At least some structure-preserving or mixed packing from structure units.
    assert modes & {
        SplitMode.STRUCTURE.value,
        SplitMode.WHOLE.value,
        SplitMode.SENTENCE.value,
        SplitMode.HARD.value,
    }
    for chunk in result.chunks:
        assert chunk.parent_path[0] == "title:5"
        assert chunk.parent_path[1] == "section:552"


def test_nested_paragraph_parent_paths(fixture_cases):
    case = next(c for c in fixture_cases if c["case_id"] == "nested-paragraph-path")
    result = run_fixture_case(case)
    assert result.chunks
    assert all(chunk.parent_path for chunk in result.chunks)
    joined_paths = ["/" + "/".join(c.parent_path) for c in result.chunks]
    assert any("section:107" in p for p in joined_paths)


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
    assert result.chunks[0].title == "35"
    assert result.chunks[0].section == "101"
    assert result.chunks[0].heading


# ---------------------------------------------------------------------------
# Module helpers / serialization
# ---------------------------------------------------------------------------


def test_chunk_to_dict_round_trip():
    result = chunk_uscode_section(
        "(a) First clause. (b) Second clause with more words here.",
        model_token_limit=16,
        title="11",
        section="101",
        overlap_tokens=2,
    )
    assert result.chunks
    payload = result.chunks[0].to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION
    from ipfs_datasets_py.processors.legal_data.uscode_chunker import LegalTextChunk

    restored = LegalTextChunk.from_mapping(payload)
    assert restored.chunk_id == result.chunks[0].chunk_id
    assert restored.chunk_cid == result.chunks[0].chunk_cid
    assert restored.exclusive_text == result.chunks[0].exclusive_text


def test_chunker_class_defaults():
    chunker = UscodeChunker()
    assert chunker.max_chunks_per_section == DEFAULT_MAX_CHUNKS_PER_SECTION
    assert chunker.tokenizer_id == DEFAULT_TOKENIZER_ID
    result = chunker.chunk_section(
        "A short provision.",
        model_token_limit=32,
        title="1",
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


def test_all_fixture_cases_execute_cleanly(fixture_cases):
    for case in fixture_cases:
        result = run_fixture_case(case)
        assert result.model_token_limit == int(case["model_token_limit"])
        assert result.schema_version == SCHEMA_VERSION
        assert result.tokenizer_id
        # Non-exempt limit enforcement always holds.
        assert_chunks_within_limit(result.chunks, result.model_token_limit)
