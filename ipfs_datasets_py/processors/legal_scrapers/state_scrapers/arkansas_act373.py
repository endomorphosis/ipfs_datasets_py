"""Exact enacted-body bridge for Arkansas Act 373, section 11.

This module is intentionally not a general Arkansas bill-PDF parser.  It
accepts one digest-pinned public act and reconstructs only Ark. Code
§ 23-4-909.  The reconstruction is independently bound to the act's printed
amendment instruction, strike/underline vector geometry, physical and printed
pagination, emergency clause, approval date, and the complete resulting text.
Any byte, coordinate, page, markup, chronology, or output drift fails closed.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

ACT373_SECTION_NUMBER = "23-4-909"
ACT373_CANDIDATE_CONTRACT = (
    (
        "AAXAABAAFAAJAAK",
        (
            "/shared/document/statutes-legislation/"
            "urn:contentItem:4WVJ-BCY0-R03N-60BF-00008-00"
        ),
    ),
    (
        "AAXAABAAFAAJAAL",
        (
            "/shared/document/statutes-legislation/"
            "urn:contentItem:6FHK-F8H0-R03M-P2W8-00008-00"
        ),
    ),
)
ACT373_DECISION_REASON = (
    "official_act373_vector_markup_and_complete_later_session_change_tables_"
    "prove_exact_current_enacted_body"
)
ACT373_URL = (
    "https://www.arkleg.state.ar.us/Acts/FTPDocument?"
    "path=%2FACTS%2F2025R%2FPublic%2F&file=373.pdf&"
    "ddBienniumSession=2025%2F2025R"
)
ACT373_SHA256 = "fa0ad2a4dd3cef14da56065a2cd128caa29cacb4db3eb7544b4a67eecf4341c4"
ACT373_BYTE_SIZE = 538_638
ACT373_PAGE_COUNT = 63
ACT373_EFFECTIVE_DATE = "2025-03-20"
ACT373_GEOMETRY_SHA256 = (
    "522ba00fc5bccb10f2d193df7555aab5bf16ac4fa61a8f46520c82b659072c81"
)
ACT373_PAGINATION_SHA256 = (
    "bd5a8e30fcb45879a99b0b564eccf219d1ba6980b25befb8e910e1c6f38748e2"
)
ACT373_AMENDMENT_INSTRUCTION_SHA256 = (
    "d41ecd3f1398129b71323b46ba7a5e2ff9470798836220845d319014d74e530a"
)
ACT373_MARKUP_GEOMETRY_SHA256 = (
    "61848e6f48ed21875bc06a3a5b8f7773043092ccbd073368f07416f6e7365eed"
)
ACT373_EFFECTIVE_DATE_GEOMETRY_SHA256 = (
    "90ad7aa341aeddfd23935b7048bf08abf4fad50f48f220ac3ac4a15a1ab7a3cf"
)
ACT373_MARK_PROJECTION_SHA256 = (
    "1137ecd61ed8691e461a2488765bb8906c3c73637a8747f3407a2533f3fe9699"
)
ACT373_CURRENT_TEXT = (
    "23-4-909. Apportionment of rates and charges.\n"
    "(a) Upon receipt of a sufficient number of valid petitions under "
    "§ 23-4-905, the Arkansas Public Service Commission may inquire into "
    "the reasonableness of the apportionment of rates and charges by a "
    "co-op.\n"
    "(b) When determining how rates and charges established under "
    "§ 23-4-903 are to be allocated among different rate classes, a co-op "
    "shall endeavor to apportion the rates and charges in a manner "
    "consistent with, as closely as practicable, the last approved "
    "cost-of-service study."
)
ACT373_CURRENT_TEXT_SHA256 = (
    "bd886059029338c2d76bc0e8027169740f96bedf6e7f9c9813d67d8746f93d85"
)

ACT373_2025_CHANGE_TABLE_URL = (
    "https://www.arkleg.state.ar.us/Acts/CodeSection?"
    "section=23&ddBienniumSession=2025%2F2025R"
)
ACT373_2025_CHANGE_TABLE_SHA256 = (
    "5178070bc931f9766f31c96ec9c54b48445e1ebb114a7cc5c85d9d0d4f9b0ec4"
)
ACT373_2025_CHANGE_TABLE_BYTE_SIZE = 1_068_635
ARKANSAS_CURRENT_SESSION_CONTRACT_URL = "https://www.arkleg.state.ar.us/Search"
ARKANSAS_CURRENT_SESSION_CONTRACT_SHA256 = (
    "bcf72c798505d420a0a355dfcfa7dafab47de73cda8ce94298c9b67279cafae4"
)
ARKANSAS_CURRENT_SESSION_CONTRACT_BYTE_SIZE = 77_806
ACT373_2026F_CHANGE_TABLE_URL = (
    "https://www.arkleg.state.ar.us/Acts/CodeSection?"
    "section=23&ddBienniumSession=2025%2F2026F"
)
ACT373_2026F_CHANGE_TABLE_SHA256 = (
    "ee56f5a91b00961947efd0004cae792deb71cddb4db48f1f49b4e310a09932b6"
)
ACT373_2026F_CHANGE_TABLE_BYTE_SIZE = 3_797
ACT373_2026S1_CHANGE_TABLE_URL = (
    "https://www.arkleg.state.ar.us/Acts/CodeSection?"
    "section=23&ddBienniumSession=2025%2F2026S1"
)
ACT373_2026S1_CHANGE_TABLE_SHA256 = (
    "69aba984cfa4fc083f7aaf2e382bc96c7cc4c20ac6891a5f330e583b46293a85"
)
ACT373_2026S1_CHANGE_TABLE_BYTE_SIZE = 354

ACT373_TEMPORAL_SOURCE_INPUT_CONTRACT = {
    "A373": (ACT373_URL, ACT373_SHA256),
    "CURRENT_SESSION": (
        ARKANSAS_CURRENT_SESSION_CONTRACT_URL,
        ARKANSAS_CURRENT_SESSION_CONTRACT_SHA256,
    ),
    "T23_2025R": (
        ACT373_2025_CHANGE_TABLE_URL,
        ACT373_2025_CHANGE_TABLE_SHA256,
    ),
    "T23_2026F": (
        ACT373_2026F_CHANGE_TABLE_URL,
        ACT373_2026F_CHANGE_TABLE_SHA256,
    ),
    "T23_2026S1": (
        ACT373_2026S1_CHANGE_TABLE_URL,
        ACT373_2026S1_CHANGE_TABLE_SHA256,
    ),
}

_EXPECTED_GEOMETRY_TEXT = {
    "semantics": (
        (
            "Stricken language would be deleted from and underlined language "
            "would be added to present law."
        ),
        "Act 373 of the Regular Session",
    ),
    "amendment_instruction": (
        "SECTION 11. Arkansas Code § 23-4-909 is amended to read as follows:",
    ),
    "next_instruction": (
        "SECTION 12. Arkansas Code § 23-4-1102 is amended to read as follows:",
    ),
    "effective_words": (
        "SECTION 31. EMERGENCY CLAUSE. It is found and determined by the",
        "General Assembly of the State of Arkansas that significant investment in",
        "electric public utility infrastructure and natural gas public utility",
        "infrastructure is required to enable this state to attract and serve economic",
        "development projects across a variety of industries, as well as to continue",
        "reliably supporting existing and new customers; that these economic",
        "development projects and the continued provision of reliable electric utility",
        "services and natural gas utility services are essential to the future of this",
        "state; and that this act is immediately necessary because strategic",
        "investments in electric public utility infrastructure and natural gas public",
        "utility infrastructure support the development of sites available for",
        "economic development projects. Therefore, an emergency is declared to exist,",
        "and this act being immediately necessary for the preservation of the public",
        "peace, health, and safety shall become effective on:",
        "(1) The date of its approval by the Governor;",
        "(2) If the bill is neither approved nor vetoed by the Governor,",
        "the expiration of the period of time during which the Governor may veto the",
        "bill; or",
        "(3) If the bill is vetoed by the Governor and the veto is",
        "overridden, the date the last house overrides the veto.",
        "APPROVED: 3/20/25",
    ),
    "pagination_words": (
        "6 03-11-2025 17:15:03 ANS209",
        "7 03-11-2025 17:15:03 ANS209",
        "62 03-11-2025 17:15:03 ANS209",
        "63 03-11-2025 17:15:03 ANS209",
    ),
}


@dataclass(frozen=True)
class ArkansasAct373EnactedSection:
    """One current section derived only from the exact enacted PDF."""

    section_number: str
    full_text: str
    full_text_sha256: str
    effective_date: str
    source_sha256: str
    source_byte_size: int
    page_count: int
    printed_pages: tuple[int, ...]
    geometry_sha256: str
    pagination_sha256: str
    amendment_instruction_sha256: str
    markup_geometry_sha256: str
    effective_date_geometry_sha256: str
    mark_projection_sha256: str
    inserted_word_count: int
    deleted_word_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArkansasAct373TemporalChain:
    """Exact official session/change-table chronology after Act 373."""

    section_number: str
    act_number: int
    measure: str
    emergency_clause: bool
    repealed: bool
    new_section: bool
    renumbered: bool
    later_sessions: tuple[str, ...]
    fiscal_2026_title_23_rows: tuple[tuple[str, str, str], ...]
    extraordinary_2026_title_23_terminal: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _rounded(value: Any) -> float:
    return round(float(value), 3)


def _word_rows(
    document: Any, page_index: int, y_values: set[float]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in document[page_index].get_text("words", sort=True):
        x0, y0, x1, y1, text, block, line, word = raw
        if _rounded(y0) not in y_values or float(x0) < 80.0:
            continue
        rows.append(
            {
                "block": int(block),
                "line": int(line),
                "page_index": page_index,
                "rect": [
                    _rounded(x0),
                    _rounded(y0),
                    _rounded(x1),
                    _rounded(y1),
                ],
                "text": str(text),
                "word": int(word),
            }
        )
    rows.sort(
        key=lambda item: (
            item["page_index"],
            item["rect"][1],
            item["rect"][0],
            item["block"],
            item["line"],
            item["word"],
        )
    )
    return rows


def _rule_rows(
    document: Any,
    page_index: int,
    minimum_y: float,
    maximum_y: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for drawing in document[page_index].get_drawings():
        rect = drawing["rect"]
        if not minimum_y <= float(rect.y0) <= maximum_y:
            continue
        rows.append(
            {
                "page_index": page_index,
                "rect": [
                    _rounded(rect.x0),
                    _rounded(rect.y0),
                    _rounded(rect.x1),
                    _rounded(rect.y1),
                ],
                "type": str(drawing.get("type") or ""),
            }
        )
    rows.sort(key=lambda item: (item["page_index"], item["rect"]))
    return rows


def extract_act373_geometry_snapshot(payload: bytes) -> dict[str, Any]:
    """Extract only the byte/coordinate facts used by the exact bridge.

    This lower-level seam intentionally does not authorize a source body.  The
    public validator below also requires the pinned content digest and every
    expected geometry/output seal.
    """

    body = bytes(payload or b"")
    if not body:
        raise ValueError("Arkansas Act 373 PDF bytes are empty")
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise RuntimeError("PyMuPDF is required for Arkansas Act 373") from exc
    try:
        document = fitz.open(stream=body, filetype="pdf")
    except Exception as exc:
        raise ValueError("Arkansas Act 373 is not a readable PDF") from exc
    try:
        page_indexes = (0, 5, 6, 61, 62)
        if len(document) <= max(page_indexes):
            raise ValueError("Arkansas Act 373 pagination is incomplete")
        snapshot = {
            "amendment_instruction": _word_rows(document, 5, {616.978}),
            "body_words": (
                _word_rows(
                    document,
                    5,
                    {634.978, 652.978, 670.978, 688.974, 706.974},
                )
                + _word_rows(
                    document,
                    6,
                    {76.898, 94.898, 112.898, 130.898},
                )
            ),
            "effective_rules": _rule_rows(document, 61, 360.0, 725.0),
            "effective_words": (
                _word_rows(
                    document,
                    61,
                    {
                        364.928,
                        382.928,
                        400.928,
                        418.928,
                        436.948,
                        454.948,
                        472.948,
                        490.948,
                        508.948,
                        526.948,
                        544.948,
                        562.948,
                        580.948,
                        598.948,
                        616.978,
                        634.978,
                        652.978,
                        670.978,
                        688.974,
                        706.974,
                    },
                )
                + _word_rows(document, 62, {148.898})
            ),
            "next_instruction": _word_rows(document, 6, {166.898}),
            "page_count": len(document),
            "page_rects": [
                {
                    "page_index": page_index,
                    "rect": [
                        _rounded(document[page_index].rect.x0),
                        _rounded(document[page_index].rect.y0),
                        _rounded(document[page_index].rect.x1),
                        _rounded(document[page_index].rect.y1),
                    ],
                }
                for page_index in range(len(document))
            ],
            "pagination_words": [
                word
                for page_index in (5, 6, 61, 62)
                for word in _word_rows(document, page_index, {735.774})
            ],
            "section_rules": (
                _rule_rows(document, 5, 650.0, 725.0)
                + _rule_rows(document, 6, 70.0, 145.0)
            ),
            "semantics": _word_rows(document, 0, {36.486, 48.006}),
        }
    finally:
        document.close()
    return snapshot


def _line_texts(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    grouped: dict[tuple[int, float], list[tuple[float, str]]] = defaultdict(list)
    for row in rows:
        page_index = int(row["page_index"])
        rect = list(row["rect"])
        if len(rect) != 4:
            raise ValueError("Arkansas Act 373 word rectangle drifted")
        grouped[(page_index, float(rect[1]))].append((float(rect[0]), str(row["text"])))
    return tuple(
        " ".join(text for _x, text in sorted(words))
        for _key, words in sorted(grouped.items())
    )


def _classify_section_words(
    snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    words = list(snapshot.get("body_words") or [])
    rules = list(snapshot.get("section_rules") or [])
    if not words or not rules:
        raise ValueError("Arkansas Act 373 section geometry is incomplete")
    marked: list[dict[str, Any]] = []
    rule_hits = [0] * len(rules)
    for raw_word in words:
        word = dict(raw_word)
        rect = [float(value) for value in list(word.get("rect") or [])]
        if len(rect) != 4:
            raise ValueError("Arkansas Act 373 word geometry drifted")
        x0, y0, x1, y1 = rect
        marks: list[str] = []
        for position, raw_rule in enumerate(rules):
            rule = dict(raw_rule)
            if int(rule.get("page_index", -1)) != int(word.get("page_index", -2)):
                continue
            rule_rect = [float(value) for value in list(rule.get("rect") or [])]
            if len(rule_rect) != 4:
                raise ValueError("Arkansas Act 373 rule geometry drifted")
            rx0, ry0, rx1, ry1 = rule_rect
            center_y = (ry0 + ry1) / 2.0
            if not y0 <= center_y <= y1 + 1.0:
                continue
            if min(x1, rx1) - max(x0, rx0) <= 0.25:
                continue
            rule_hits[position] += 1
            if center_y >= y1 - 2.0:
                marks.append("underline")
            elif y0 + 2.0 <= center_y < y1 - 2.0:
                marks.append("strike")
            else:
                marks.append("invalid")
        unique_marks = set(marks)
        if "invalid" in unique_marks or len(unique_marks) > 1:
            raise ValueError("Arkansas Act 373 word has ambiguous markup")
        marked.append(
            {
                "mark": marks[0] if marks else "plain",
                "page_index": int(word["page_index"]),
                "rect": list(word["rect"]),
                "text": str(word["text"]),
            }
        )
    if any(count == 0 for count in rule_hits):
        raise ValueError("Arkansas Act 373 markup rule is not text-bound")
    return marked


def _join_tokens(tokens: Sequence[str]) -> str:
    joined: list[str] = []
    for token in tokens:
        # These are the only two printed line-break hyphens in the exact
        # section.  General lexical dehyphenation is deliberately forbidden.
        if joined and joined[-1] in {"23-", "23-4-"}:
            joined[-1] += token
        else:
            joined.append(token)
    return " ".join(joined)


def derive_act373_enacted_section_from_snapshot(
    snapshot: Mapping[str, Any],
) -> ArkansasAct373EnactedSection:
    """Validate one geometry snapshot and apply only its official markup."""

    normalized_snapshot = json.loads(
        json.dumps(
            dict(snapshot),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    pagination_sha256 = _canonical_sha256(
        {
            key: normalized_snapshot.get(key)
            for key in ("page_count", "page_rects", "pagination_words")
        }
    )
    if pagination_sha256 != ACT373_PAGINATION_SHA256:
        raise ValueError("Arkansas Act 373 pagination projection drifted")
    amendment_instruction_sha256 = _canonical_sha256(
        {
            key: normalized_snapshot.get(key)
            for key in ("semantics", "amendment_instruction", "next_instruction")
        }
    )
    if amendment_instruction_sha256 != ACT373_AMENDMENT_INSTRUCTION_SHA256:
        raise ValueError("Arkansas Act 373 amendment instruction drifted")
    markup_geometry_sha256 = _canonical_sha256(
        {key: normalized_snapshot.get(key) for key in ("body_words", "section_rules")}
    )
    if markup_geometry_sha256 != ACT373_MARKUP_GEOMETRY_SHA256:
        raise ValueError("Arkansas Act 373 markup geometry drifted")
    effective_date_geometry_sha256 = _canonical_sha256(
        {
            key: normalized_snapshot.get(key)
            for key in ("effective_words", "effective_rules")
        }
    )
    if effective_date_geometry_sha256 != ACT373_EFFECTIVE_DATE_GEOMETRY_SHA256:
        raise ValueError("Arkansas Act 373 effective-date geometry drifted")
    geometry_sha256 = _canonical_sha256(normalized_snapshot)
    if geometry_sha256 != ACT373_GEOMETRY_SHA256:
        raise ValueError("Arkansas Act 373 geometry projection drifted")
    if int(normalized_snapshot.get("page_count") or 0) != ACT373_PAGE_COUNT:
        raise ValueError("Arkansas Act 373 page count drifted")
    expected_page_rects = [
        {"page_index": page_index, "rect": [0.0, 0.0, 612.0, 792.0]}
        for page_index in range(ACT373_PAGE_COUNT)
    ]
    if normalized_snapshot.get("page_rects") != expected_page_rects:
        raise ValueError("Arkansas Act 373 physical pagination drifted")
    for key, expected in _EXPECTED_GEOMETRY_TEXT.items():
        if _line_texts(normalized_snapshot.get(key) or []) != expected:
            raise ValueError(f"Arkansas Act 373 {key} text drifted")

    marked = _classify_section_words(normalized_snapshot)
    mark_projection_sha256 = _canonical_sha256(marked)
    if mark_projection_sha256 != ACT373_MARK_PROJECTION_SHA256:
        raise ValueError("Arkansas Act 373 strike/underline projection drifted")

    by_line: dict[tuple[int, float], list[str]] = defaultdict(list)
    inserted_word_count = 0
    deleted_word_count = 0
    for word in marked:
        mark = str(word["mark"])
        inserted_word_count += mark == "underline"
        deleted_word_count += mark == "strike"
        if mark == "strike":
            continue
        rect = list(word["rect"])
        by_line[(int(word["page_index"]), float(rect[1]))].append(str(word["text"]))
    ordered_lines = [tokens for _key, tokens in sorted(by_line.items())]
    if len(ordered_lines) != 9:
        raise ValueError("Arkansas Act 373 section line count drifted")
    heading = _join_tokens(ordered_lines[0])
    subsection_a: list[str] = []
    subsection_b: list[str] = []
    destination = subsection_a
    for tokens in ordered_lines[1:]:
        if tokens and tokens[0] == "(b)":
            destination = subsection_b
        destination.extend(tokens)
    if not subsection_a or not subsection_b:
        raise ValueError("Arkansas Act 373 subsection boundary drifted")
    full_text = "\n".join(
        (
            heading,
            _join_tokens(subsection_a),
            _join_tokens(subsection_b),
        )
    )
    full_text_sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    if (
        full_text != ACT373_CURRENT_TEXT
        or full_text_sha256 != ACT373_CURRENT_TEXT_SHA256
    ):
        raise ValueError("Arkansas Act 373 resulting enacted text drifted")
    if (inserted_word_count, deleted_word_count) != (41, 9):
        raise ValueError("Arkansas Act 373 markup word counts drifted")

    return ArkansasAct373EnactedSection(
        section_number=ACT373_SECTION_NUMBER,
        full_text=full_text,
        full_text_sha256=full_text_sha256,
        effective_date=ACT373_EFFECTIVE_DATE,
        source_sha256=ACT373_SHA256,
        source_byte_size=ACT373_BYTE_SIZE,
        page_count=ACT373_PAGE_COUNT,
        printed_pages=(6, 7, 62, 63),
        geometry_sha256=geometry_sha256,
        pagination_sha256=pagination_sha256,
        amendment_instruction_sha256=amendment_instruction_sha256,
        markup_geometry_sha256=markup_geometry_sha256,
        effective_date_geometry_sha256=effective_date_geometry_sha256,
        mark_projection_sha256=mark_projection_sha256,
        inserted_word_count=inserted_word_count,
        deleted_word_count=deleted_word_count,
    )


def validate_act373_enacted_section(
    payload: bytes,
) -> ArkansasAct373EnactedSection:
    """Validate and reconstruct exact current § 23-4-909 from Act 373."""

    body = bytes(payload or b"")
    if len(body) != ACT373_BYTE_SIZE:
        raise ValueError("Arkansas Act 373 byte size drifted")
    if hashlib.sha256(body).hexdigest() != ACT373_SHA256:
        raise ValueError("Arkansas Act 373 SHA-256 drifted")
    snapshot = extract_act373_geometry_snapshot(body)
    return derive_act373_enacted_section_from_snapshot(snapshot)


def _validate_exact_html(
    payload: bytes,
    *,
    label: str,
    expected_sha256: str,
    expected_byte_size: int,
) -> bytes:
    body = bytes(payload or b"")
    if len(body) != expected_byte_size:
        raise ValueError(f"{label} byte size drifted")
    if hashlib.sha256(body).hexdigest() != expected_sha256:
        raise ValueError(f"{label} SHA-256 drifted")
    return body


def _normalized_text(node: Any) -> str:
    return " ".join(str(node.get_text(" ", strip=True) or "").split())


def _change_table_rows(soup: Any) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for row in soup.select("div.row.tableRow, div.row.tableRowAlt"):
        cells = row.find_all("div", role="gridcell", recursive=False)
        if len(cells) != 7:
            raise ValueError("Arkansas title 23 change-table row shape drifted")
        desktop_code = cells[0].select("div[aria-hidden='true']")
        if len(desktop_code) != 2:
            raise ValueError("Arkansas title 23 code cell shape drifted")
        code_number = _normalized_text(desktop_code[-1])
        act_links = cells[1].find_all("a", href=True)
        measure_links = cells[6].find_all("a", href=True)
        if len(act_links) != 2 or len(measure_links) != 2:
            raise ValueError("Arkansas title 23 change-table links drifted")
        act_facts = {
            (
                _normalized_text(link),
                str(link.get("href") or ""),
                str(link.get("aria-label") or ""),
            )
            for link in act_links
        }
        measure_facts = {
            (_normalized_text(link), str(link.get("href") or ""))
            for link in measure_links
        }
        if len(act_facts) != 1 or len(measure_facts) != 1:
            raise ValueError("Arkansas title 23 duplicated link facts drifted")
        act_number, act_href, act_label = next(iter(act_facts))
        measure, measure_href = next(iter(measure_facts))
        mobile_flags = []
        for cell in cells[2:6]:
            mobile = cell.select("div.d-sm-block[aria-hidden='true']")
            if len(mobile) != 1:
                raise ValueError("Arkansas title 23 flag cell shape drifted")
            mobile_flags.append(_normalized_text(mobile[0]))
        parsed.append(
            {
                "act_href": act_href,
                "act_label": act_label,
                "act_number": act_number,
                "code_number": code_number,
                "emergency": mobile_flags[0],
                "measure": measure,
                "measure_href": measure_href,
                "new_section": mobile_flags[2],
                "renumbered": mobile_flags[3],
                "repealed": mobile_flags[1],
            }
        )
    return parsed


def validate_act373_temporal_chain(
    *,
    change_table_2025: bytes,
    current_session_contract: bytes,
    change_table_2026f: bytes,
    change_table_2026s1: bytes,
) -> ArkansasAct373TemporalChain:
    """Prove Act 373 is the latest title-23 amendment to § 23-4-909."""

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise RuntimeError("BeautifulSoup is required for Arkansas Act 373") from exc

    bodies = {
        "2025": _validate_exact_html(
            change_table_2025,
            label="Arkansas 2025R title 23 change table",
            expected_sha256=ACT373_2025_CHANGE_TABLE_SHA256,
            expected_byte_size=ACT373_2025_CHANGE_TABLE_BYTE_SIZE,
        ),
        "sessions": _validate_exact_html(
            current_session_contract,
            label="Arkansas current session contract",
            expected_sha256=ARKANSAS_CURRENT_SESSION_CONTRACT_SHA256,
            expected_byte_size=ARKANSAS_CURRENT_SESSION_CONTRACT_BYTE_SIZE,
        ),
        "2026F": _validate_exact_html(
            change_table_2026f,
            label="Arkansas 2026F title 23 change table",
            expected_sha256=ACT373_2026F_CHANGE_TABLE_SHA256,
            expected_byte_size=ACT373_2026F_CHANGE_TABLE_BYTE_SIZE,
        ),
        "2026S1": _validate_exact_html(
            change_table_2026s1,
            label="Arkansas 2026S1 title 23 change table",
            expected_sha256=ACT373_2026S1_CHANGE_TABLE_SHA256,
            expected_byte_size=ACT373_2026S1_CHANGE_TABLE_BYTE_SIZE,
        ),
    }
    soup_2025 = BeautifulSoup(bodies["2025"], "html.parser")
    rows_2025 = [
        row
        for row in _change_table_rows(soup_2025)
        if row["code_number"] == ACT373_SECTION_NUMBER
    ]
    if len(rows_2025) != 1:
        raise ValueError("Arkansas 2025R § 23-4-909 row is not unique")
    row_2025 = rows_2025[0]
    expected_2025 = {
        "act_href": (
            "/Acts/FTPDocument?path=%2FACTS%2F2025R%2FPublic%2F&"
            "file=373.pdf&ddBienniumSession=2025%2F2025R"
        ),
        "act_label": "Act373.PDF",
        "act_number": "373",
        "code_number": ACT373_SECTION_NUMBER,
        "emergency": "Emergency Clause: Yes",
        "measure": "SB307",
        "measure_href": ("/Bills/Detail?id=SB307&ddBienniumSession=2025%2F2025R"),
        "new_section": "New Section: No",
        "renumbered": "Renumbered: No",
        "repealed": "Repealed: No",
    }
    if row_2025 != expected_2025:
        raise ValueError("Arkansas 2025R § 23-4-909 amendment row drifted")

    session_soup = BeautifulSoup(bodies["sessions"], "html.parser")
    expected_session_options = (
        ("2025/2026S1", "2025 - First Extraordinary Session, 2026", False),
        ("2025/2026F", "2025 - Fiscal Session, 2026", True),
        ("2025/2025R", "2025 - Regular Session, 2025", False),
    )
    for select_id in (
        "ddBienniumSessionBillsQuickFind",
        "ddBienniumSessionActsQuickFind",
    ):
        select = session_soup.find("select", id=select_id)
        if select is None:
            raise ValueError("Arkansas current session selector is missing")
        options = [
            (
                str(option.get("value") or ""),
                _normalized_text(option),
                option.has_attr("selected"),
            )
            for option in select.find_all("option", recursive=False)
            if str(option.get("value") or "")
        ]
        if tuple(options[:3]) != expected_session_options:
            raise ValueError("Arkansas current session frontier drifted")
        if [
            value for value, _text, _selected in options if value.startswith("2025/")
        ] != [value for value, _text, _selected in expected_session_options]:
            raise ValueError("Arkansas current biennium session set drifted")

    soup_2026f = BeautifulSoup(bodies["2026F"], "html.parser")
    rows_2026f = _change_table_rows(soup_2026f)
    expected_2026f = {
        "act_href": (
            "/Acts/FTPDocument?path=%2FACTS%2F2026F%2FPublic%2F&"
            "file=147.pdf&ddBienniumSession=2025%2F2026F"
        ),
        "act_label": "Act147.PDF",
        "act_number": "147",
        "code_number": "23-86-119(a)(1)",
        "emergency": "Emergency Clause: Yes",
        "measure": "SB7",
        "measure_href": "/Bills/Detail?id=SB7&ddBienniumSession=2025%2F2026F",
        "new_section": "New Section: No",
        "renumbered": "Renumbered: No",
        "repealed": "Repealed: No",
    }
    if rows_2026f != [expected_2026f]:
        raise ValueError("Arkansas 2026F title 23 amendment frontier drifted")

    soup_2026s1 = BeautifulSoup(bodies["2026S1"], "html.parser")
    errors = [_normalized_text(node) for node in soup_2026s1.select(".errormessage")]
    if _change_table_rows(soup_2026s1) or errors != [
        "No amended code for this section."
    ]:
        raise ValueError("Arkansas 2026S1 title 23 terminal drifted")

    return ArkansasAct373TemporalChain(
        section_number=ACT373_SECTION_NUMBER,
        act_number=373,
        measure="SB307",
        emergency_clause=True,
        repealed=False,
        new_section=False,
        renumbered=False,
        later_sessions=("2025/2026F", "2025/2026S1"),
        fiscal_2026_title_23_rows=(("23-86-119(a)(1)", "147", "SB7"),),
        extraordinary_2026_title_23_terminal=("No amended code for this section."),
    )


__all__ = [
    "ACT373_2025_CHANGE_TABLE_BYTE_SIZE",
    "ACT373_2025_CHANGE_TABLE_SHA256",
    "ACT373_2025_CHANGE_TABLE_URL",
    "ACT373_2026F_CHANGE_TABLE_BYTE_SIZE",
    "ACT373_2026F_CHANGE_TABLE_SHA256",
    "ACT373_2026F_CHANGE_TABLE_URL",
    "ACT373_2026S1_CHANGE_TABLE_BYTE_SIZE",
    "ACT373_2026S1_CHANGE_TABLE_SHA256",
    "ACT373_2026S1_CHANGE_TABLE_URL",
    "ACT373_AMENDMENT_INSTRUCTION_SHA256",
    "ACT373_BYTE_SIZE",
    "ACT373_CANDIDATE_CONTRACT",
    "ACT373_CURRENT_TEXT",
    "ACT373_CURRENT_TEXT_SHA256",
    "ACT373_DECISION_REASON",
    "ACT373_EFFECTIVE_DATE",
    "ACT373_EFFECTIVE_DATE_GEOMETRY_SHA256",
    "ACT373_GEOMETRY_SHA256",
    "ACT373_MARKUP_GEOMETRY_SHA256",
    "ACT373_MARK_PROJECTION_SHA256",
    "ACT373_PAGE_COUNT",
    "ACT373_PAGINATION_SHA256",
    "ACT373_SECTION_NUMBER",
    "ACT373_SHA256",
    "ACT373_TEMPORAL_SOURCE_INPUT_CONTRACT",
    "ACT373_URL",
    "ARKANSAS_CURRENT_SESSION_CONTRACT_BYTE_SIZE",
    "ARKANSAS_CURRENT_SESSION_CONTRACT_SHA256",
    "ARKANSAS_CURRENT_SESSION_CONTRACT_URL",
    "ArkansasAct373EnactedSection",
    "ArkansasAct373TemporalChain",
    "derive_act373_enacted_section_from_snapshot",
    "extract_act373_geometry_snapshot",
    "validate_act373_enacted_section",
    "validate_act373_temporal_chain",
]
