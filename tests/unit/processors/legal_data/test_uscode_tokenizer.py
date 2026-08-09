"""Unit tests for the versioned legal BM25 tokenizer (USCIR-013).

Acceptance:

* Tokenization is locale-independent.
* Output is bounded.
* Results are stable across fixtures.
* Offsets are reversible enough for explanations.
* Legally meaningful numeric/citation tokens are distinguished.
"""

from __future__ import annotations

import json
import locale
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (
    DEFAULT_MAX_TOKEN_CHARS,
    DEFAULT_STOPWORDS,
    FIXTURE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    STOPWORD_POLICY_ID,
    TASK_ID,
    TOKENIZER_ID,
    TOKENIZER_VERSION,
    LegalToken,
    TokenKind,
    TokenizationFixtureError,
    TokenizerConfig,
    TokenizerConfigError,
    UscodeTokenizerError,
    assert_case_expectations,
    assert_offsets_recover_surface,
    build_default_tokenization_fixture_payload,
    canonicalize_citation_term,
    default_tokenization_fixture_path,
    default_tokenizer_config,
    explain_tokens,
    legal_tokens_present,
    load_tokenization_fixture_payload,
    normalize_legal_text,
    reconstruct_from_tokens,
    run_all_fixture_cases,
    run_fixture_case,
    term_frequencies,
    tokenize_legal_text,
    tokenize_terms,
    tokenize_uscode,
    tokenizer_identity,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "uscode_tokenization.json"
)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return load_tokenization_fixture_payload(_FIXTURE_PATH)


@pytest.fixture(scope="module")
def fixture_cases(fixture_payload: dict) -> list[dict]:
    return list(fixture_payload["cases"])


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_tokenization_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_tokenization_fixture_path().name == "uscode_tokenization.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 64_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["tokenizer_id"] == TOKENIZER_ID
    assert payload["tokenizer_version"] == TOKENIZER_VERSION
    assert payload["stopword_policy_id"] == STOPWORD_POLICY_ID
    assert payload["task_id"] == TASK_ID
    assert isinstance(payload["cases"], list)
    assert len(payload["cases"]) >= 8
    # Recipe form: no bulk per-token golden dumps.
    for case in payload["cases"]:
        assert "case_id" in case
        assert "expect" in case
        assert "tokens" not in case
        assert "golden_terms" not in case


def test_default_payload_matches_on_disk_recipe():
    built = build_default_tokenization_fixture_payload()
    on_disk = load_tokenization_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["tokenizer_id"] == on_disk["tokenizer_id"]
    built_ids = [c["case_id"] for c in built["cases"]]
    disk_ids = [c["case_id"] for c in on_disk["cases"]]
    assert built_ids == disk_ids


def test_malformed_fixture_rejected(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"schema_version": "nope", "cases": []}),
        encoding="utf-8",
    )
    with pytest.raises(TokenizationFixtureError):
        load_tokenization_fixture_payload(bad)


def test_all_fixture_cases_pass(fixture_cases: list[dict]):
    for case in fixture_cases:
        result = run_fixture_case(case)
        assert_case_expectations(case, result)


def test_run_all_fixture_cases_helper():
    results = run_all_fixture_cases(_FIXTURE_PATH)
    assert len(results) >= 8
    assert all(case_id for case_id, _ in results)


# ---------------------------------------------------------------------------
# Identity / configuration
# ---------------------------------------------------------------------------


def test_tokenizer_identity_pinned():
    identity = tokenizer_identity()
    assert identity["tokenizer_id"] == "uscode-bm25-tokenizer/v1"
    assert identity["tokenizer_version"] == "v1"
    assert identity["schema_version"] == SCHEMA_VERSION
    assert identity["stopword_policy_id"] == STOPWORD_POLICY_ID
    assert len(identity["tokenizer_digest"]) == 64


def test_unsupported_tokenizer_id_rejected():
    with pytest.raises(TokenizerConfigError):
        TokenizerConfig(tokenizer_id="other-tokenizer/v1")


def test_default_config_bounds():
    cfg = default_tokenizer_config()
    assert cfg.max_token_chars == DEFAULT_MAX_TOKEN_CHARS
    assert cfg.drop_stopwords is True
    assert "the" in cfg.stopwords
    assert "section" not in cfg.stopwords


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalize_nfkc_and_dashes():
    raw = "1001\u20131003 \ufb01le"  # en-dash + fi ligature
    normalized = normalize_legal_text(raw)
    assert "\u2013" not in normalized
    assert "1001-1003" in normalized
    # NFKC expands the fi ligature.
    assert "fi" in normalized or "file" in normalized or "ﬁ" not in normalized


def test_normalize_strips_controls_preserves_newline():
    raw = "line1\nline2\x07tab\there"
    normalized = normalize_legal_text(raw)
    assert "\x07" not in normalized
    assert "\n" in normalized
    assert "line1" in normalized and "line2" in normalized


def test_normalize_rejects_nul_and_non_string():
    with pytest.raises(UscodeTokenizerError):
        normalize_legal_text("bad\x00text")
    with pytest.raises(UscodeTokenizerError):
        normalize_legal_text(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Legal citation / numeric distinction
# ---------------------------------------------------------------------------


def test_usc_citation_survives_as_single_token():
    text = "Disclosure under 5 U.S.C. § 552(a)(1) is mandatory."
    result = tokenize_legal_text(text, drop_stopwords=True)
    citations = [t for t in result.tokens if t.kind == TokenKind.CITATION]
    assert len(citations) == 1
    assert "5_u.s.c." in citations[0].term
    assert "552" in citations[0].term
    # Must not be split into bare "5" + "u" + "s" + "c" + "552" only.
    assert citations[0].term.count("_") >= 2


def test_compact_usc_and_section_symbol():
    text = "Compare 17 USC 107 with § 106 and section 230."
    terms = tokenize_terms(text)
    joined = " ".join(terms)
    assert "17_u.s.c." in joined
    assert any(t.startswith("§_") or "§" in t for t in terms)
    assert any("section_230" in t or t == "section_230" for t in terms)


def test_numeric_tokens_distinguished_from_words():
    text = "Sections 1983 and 12101a authorize civil actions."
    result = tokenize_legal_text(text, drop_stopwords=False)
    kinds = {t.term: t.kind for t in result.tokens}
    # section_ref absorbs "Sections 1983"; 12101a may be number or part of ref.
    assert any(t.kind == TokenKind.SECTION_REF for t in result.tokens) or any(
        t.kind == TokenKind.NUMBER for t in result.tokens
    )
    numberish = [
        t for t in result.tokens if t.kind in {TokenKind.NUMBER, TokenKind.SECTION_REF}
    ]
    assert numberish
    assert any("1983" in t.term or "12101a" in t.term for t in numberish)


def test_legal_tokens_present_helper():
    text = "35 U.S.C. § 101 and § 103 govern patentability."
    protected = legal_tokens_present(text)
    assert protected
    assert any("35_u.s.c." in t for t in protected)


def test_canonicalize_citation_term_stable():
    a = canonicalize_citation_term("5 U.S.C. § 552")
    b = canonicalize_citation_term("5 usc § 552")
    c = canonicalize_citation_term("5 U. S. C. § 552")
    assert a == b == c
    assert a == "5_u.s.c._§_552"
    assert ".." not in a


# ---------------------------------------------------------------------------
# Stopword policy
# ---------------------------------------------------------------------------


def test_stopwords_dropped_for_index_stream():
    text = "The agency shall make available to the public the records."
    terms = tokenize_terms(text)
    assert "the" not in terms
    assert "to" not in terms
    assert "agency" in terms
    assert "public" in terms
    assert "records" in terms


def test_stopwords_retained_for_explanations():
    text = "The agency shall disclose."
    result = tokenize_legal_text(text, drop_stopwords=False)
    stop = [t for t in result.tokens if t.kind == TokenKind.STOPWORD]
    assert stop
    assert any(t.term == "the" for t in stop)
    assert all(not t.is_indexable for t in stop)


def test_citations_never_stopworded():
    # Even if a stopword list were aggressive, protected kinds stay indexable.
    cfg = TokenizerConfig(stopwords=DEFAULT_STOPWORDS | frozenset({"5"}))
    result = tokenize_legal_text("See 5 U.S.C. § 552.", config=cfg, drop_stopwords=True)
    assert any(t.kind == TokenKind.CITATION and t.is_indexable for t in result.tokens)


# ---------------------------------------------------------------------------
# Offsets / reversibility for explanations
# ---------------------------------------------------------------------------


def test_offsets_recover_surface_spans():
    text = "FOIA under 5 U.S.C. § 552(a) and section 230."
    result = tokenize_legal_text(text, drop_stopwords=False)
    assert_offsets_recover_surface(result)
    for token in result.tokens:
        span = result.normalized_text[token.char_start : token.char_end]
        assert span == token.surface


def test_explain_tokens_include_span_text():
    text = "28 U.S.C. § 1331 federal question"
    explained = explain_tokens(text, drop_stopwords=True)
    assert explained
    assert all("span_text" in row for row in explained)
    assert any(row["kind"] == "citation" for row in explained)


def test_reconstruct_from_tokens_joins_surfaces():
    tokens = tokenize_uscode("agency records", drop_stopwords=True)
    assert reconstruct_from_tokens(tokens) == "agency records"


def test_positions_are_dense_for_indexable_tokens():
    result = tokenize_legal_text(
        "The public agency discloses records.",
        drop_stopwords=True,
    )
    positions = [t.position for t in result.tokens if t.is_indexable]
    assert positions == list(range(len(positions)))


# ---------------------------------------------------------------------------
# Locale independence & stability
# ---------------------------------------------------------------------------


def test_locale_independent_casefold():
    text = "FREEDOM of Information under 5 U.S.C. § 552"
    base = tokenize_terms(text)
    try:
        previous = locale.setlocale(locale.LC_ALL)
    except locale.Error:
        previous = None
    try:
        for candidate in ("C", "C.UTF-8", "POSIX"):
            try:
                locale.setlocale(locale.LC_ALL, candidate)
            except locale.Error:
                continue
            assert tokenize_terms(text) == base
            assert tokenize_terms(text.upper()) == base
            assert tokenize_terms(text.casefold()) == base
    finally:
        if previous is not None:
            try:
                locale.setlocale(locale.LC_ALL, previous)
            except locale.Error:
                pass


def test_deterministic_across_repeated_calls():
    text = "42 U.S.C. § 1983 civil action — deprivation of rights"
    first = tokenize_legal_text(text).to_dict()
    for _ in range(5):
        assert tokenize_legal_text(text).to_dict() == first


def test_term_frequencies_stable():
    text = "agency agency public records"
    freq = term_frequencies(text)
    assert freq["agency"] == 2
    assert freq["public"] == 1
    assert freq["records"] == 1


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


def test_max_tokens_bound_and_truncated_flag():
    text = " ".join(["provision"] * 40)
    cfg = TokenizerConfig(max_tokens=10)
    result = tokenize_legal_text(text, config=cfg, drop_stopwords=True)
    assert result.indexable_count == 10
    assert result.truncated is True
    assert result.token_count == 10


def test_max_token_chars_truncates_long_term():
    long_word = "a" * 200
    cfg = TokenizerConfig(max_token_chars=32)
    terms = tokenize_terms(long_word, config=cfg)
    assert len(terms) == 1
    assert len(terms[0]) == 32


def test_empty_input_yields_empty_stream():
    result = tokenize_legal_text("   \n\t  ")
    assert result.token_count == 0
    assert result.indexable_terms == ()
    assert result.truncated is False


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def test_legal_token_roundtrip_dict():
    token = LegalToken(
        index=0,
        position=0,
        term="agency",
        surface="Agency",
        kind=TokenKind.WORD,
        char_start=0,
        char_end=6,
    )
    restored = LegalToken.from_dict(token.to_dict())
    assert restored == token
