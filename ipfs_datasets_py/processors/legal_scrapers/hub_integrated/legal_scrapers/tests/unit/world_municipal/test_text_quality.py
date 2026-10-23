"""Unit tests for the extraction-usability gate (text_quality module).

Ported from the Italy pilot's harvester gate (Levico Terme incident,
2026-10-14): a no-ToUnicode PDF whose PyMuPDF output was 73% control
chars and whose pdfplumber output was literal (cid:N) tokens — both
passed length checks and validate_table. Cases (a)-(d) are the brief's:
garbage rejected, cid-token text rejected, clean digital text
accepted, clean OCR text accepted.
"""

import pytest

_PROSE = (
    "The council of the municipality hereby decrees the following rules "
    "for the use of public roads and squares within the town boundaries. "
    "Article one applies to all residents and visitors alike, and the "
    "mayor is charged with the enforcement of these provisions. "
)


def _clean_text(reps=10):
    return _PROSE * reps


def test_thresholds_match_italy_pilot(wm):
    tq = wm.text_quality
    assert tq.MIN_TEXT_CHARS == 300
    assert tq.MAX_CONTROL_RATIO == 0.02
    assert tq.CID_TOKEN_CHAR_BUDGET == 2000
    assert tq.MIN_LETTER_SHARE == 0.45


def test_empty_and_short_text_rejected(wm):
    tq = wm.text_quality
    assert tq.garble_ratio("") == 1.0
    assert not tq.is_usable_text("")
    assert not tq.is_usable_text("   \n  ")
    assert not tq.is_usable_text("Short but perfectly clean text.")
    assert tq.usability_failures("") == ["empty text"]


def test_control_char_garbage_rejected(wm):
    """(a) Glyph garbage: letters interleaved with control chars."""
    tq = wm.text_quality
    chars = list(_clean_text(30))
    for i in range(0, len(chars), 10):
        chars[i] = "\x02"
    garbage = "".join(chars)
    assert tq.garble_ratio(garbage) > 0.02
    assert not tq.is_usable_text(garbage)
    failures = tq.usability_failures(garbage)
    # isolated leg: letter share still passes, only the control leg fires
    assert len(failures) == 1 and "control" in failures[0]


def test_control_ratio_boundary_matches_pilot(wm):
    """Ratio exactly at the 2% cap passes (pilot rule is strict >)."""
    tq = wm.text_quality
    text = "a" * 980 + "\x01" * 20
    assert tq.garble_ratio(text) == 0.02
    assert tq.is_usable_text(text)


def test_cid_token_text_rejected(wm):
    """(b) pdfplumber output for a no-ToUnicode PDF: literal (cid:N)."""
    tq = wm.text_quality
    cid_stream = "(cid:123) " * 60
    assert not tq.is_usable_text(cid_stream)
    assert any("(cid:" in f for f in tq.usability_failures(cid_stream))


def test_cid_density_leg_isolated(wm):
    """Clean prose with too many (cid: tokens fails on that leg alone."""
    tq = wm.text_quality
    text = _clean_text(80) + " (cid:45)" * 12
    assert tq.cid_token_count(text) == 12
    assert len(text) / 2000 < 12  # over the density cap
    failures = tq.usability_failures(text)
    assert len(failures) == 1 and "(cid:" in failures[0]
    assert not tq.is_usable_text(text)


def test_clean_born_digital_text_accepted(wm):
    """(c) Ordinary born-digital legal prose passes every leg."""
    tq = wm.text_quality
    text = _clean_text()
    assert tq.usability_failures(text) == []
    assert tq.is_usable_text(text)
    assert tq.assert_usable_text(text) == text


def test_clean_ocr_text_accepted(wm):
    """(d) OCR output with typical recognition noise still passes.

    Modelled on the pilot's Levico recovery: real prose, a few
    digit-for-letter substitutions and irregular spacing, no control
    chars, letter share comfortably above the floor.
    """
    tq = wm.text_quality
    ocr_text = (
        "COMUNE DI LEVICO TERME\n"
        "REGOLAMENTO COMUNALE PER L'EROGAZIONE DI FINANZIAMENTI E "
        "L'ATTRIBUZIONE DI BENEFICI ECONOMICI\n\n"
        "Artico1o 1 — Oggetto\n"
        "Il presente regolamento disciplina i criteri e le modalita per "
        "la concessione di finanziamenti e benefici economici a persone "
        "fisiche, enti e associazioni operanti nel territorio comunale. "
        "Le domande devono essere presentate entro i termini stabiliti "
        "dal bando annuale approvato dalla giunta comunale, corredate "
        "dalla documentazione prevista dal presente rego1amento. "
        "L'ufficio competente provvede all'istruttoria e trasmette gli "
        "atti alla commissione per la valutazione di merito. "
    )
    assert tq.is_usable_text(ocr_text)
    assert tq.usability_failures(ocr_text) == []


def test_letter_share_leg(wm):
    """A numeric-table dump (few letters) fails the letter-share leg."""
    tq = wm.text_quality
    table = " ".join(f"{i} {i * 7}.50 {1000 + i}" for i in range(120))
    assert len(table.strip()) >= 300
    failures = tq.usability_failures(table)
    assert any("letter share" in f for f in failures)
    assert not tq.is_usable_text(table)


def test_assert_usable_text_raises_on_garbage(wm):
    tq = wm.text_quality
    with pytest.raises(ValueError, match="usability gate failed"):
        tq.assert_usable_text("\x01\x02\x03" * 200, context="doc 42")


def test_first_usable_extraction_falls_through(wm):
    """Failed candidates count as NOT extracted; the chain falls through
    to the first usable method (in practice: OCR), or to None (defer)."""
    tq = wm.text_quality
    garbage = "\x02".join(list(_clean_text(5)))
    cid_text = "(cid:9) " * 80
    clean = _clean_text()
    picked = tq.first_usable_extraction(
        [("pymupdf", garbage), ("pdfplumber", cid_text), ("ocr", clean)]
    )
    assert picked == ("ocr", clean)
    assert tq.first_usable_extraction([("pymupdf", garbage)]) is None
    assert tq.first_usable_extraction([]) is None
    # first usable wins; later candidates are not consulted
    assert tq.first_usable_extraction(
        [("pymupdf", clean), ("ocr", garbage)]
    ) == ("pymupdf", clean)
