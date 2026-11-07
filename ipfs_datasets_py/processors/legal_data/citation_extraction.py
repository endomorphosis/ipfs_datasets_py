"""Citation extraction and linking for legal documents.

This module provides comprehensive citation extraction capabilities for legal texts,
including case law, statutes, regulations, and cross-references.
"""

from __future__ import annotations

import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from ipfs_datasets_py.processors.legal_data.citation_forms import (
    iter_journal_spans,
    iter_parallel_reporter_spans,
    iter_spelled_reporter_spans,
)
from ipfs_datasets_py.processors.legal_data.citation_reporters import iter_case_spans

logger = logging.getLogger(__name__)


def _overlaps(left: Citation, right: Citation) -> bool:
    return left.start_pos < right.end_pos and right.start_pos < left.end_pos


def _contained(inner: Citation, outer: Citation) -> bool:
    return (
        inner.start_pos >= outer.start_pos
        and inner.end_pos <= outer.end_pos
        and (inner.end_pos - inner.start_pos) < (outer.end_pos - outer.start_pos)
    )


def _prefer_longer(citations: List[Citation]) -> List[Citation]:
    """Drop a citation that sits inside a longer one.

    A parallel cite such as ``4 U.S. (4 Dall.) 1`` is two citations on the
    same span, so equal spans are kept. A shorter cite inside a longer one
    is not.
    """
    ordered = sorted(citations, key=lambda item: (item.end_pos - item.start_pos, item.start_pos), reverse=True)
    kept: List[Citation] = []
    for citation in ordered:
        if any(_contained(citation, previous) for previous in kept):
            continue
        if any(
            citation.start_pos == previous.start_pos
            and citation.end_pos == previous.end_pos
            and citation.type == previous.type
            and citation.text == previous.text
            for previous in kept
        ):
            continue
        kept.append(citation)
    kept.sort(key=lambda item: (item.start_pos, item.end_pos, item.text))
    return kept


@dataclass
class Citation:
    """Represents a legal citation."""

    type: str  # "case", "journal", "usc", "state_statute", "cfr", "federal_register", "rule"
    text: str  # Full citation text as it appears
    reporter: Optional[str] = None  # e.g., "F.3d", "U.S."
    volume: Optional[str] = None
    page: Optional[str] = None
    year: Optional[str] = None
    title: Optional[str] = None  # For statutes/regulations
    section: Optional[str] = None
    court: Optional[str] = None
    url: Optional[str] = None  # Link to source if available
    jurisdiction: Optional[str] = None  # e.g. "MN", "US"
    start_pos: int = 0  # Character position in source text
    end_pos: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# Citation patterns
CASE_CITATION_PATTERNS = [
    # Federal reporters: e.g., "123 F.3d 456"
    r"(\d+)\s+(F\.\s?(?:2d|3d|4th|App\'?x?))\s+(\d+)",
    # U.S. Reports: e.g., "123 U.S. 456"
    r"(\d+)\s+(U\.S\.)\s+(\d+)",
    # Supreme Court: e.g., "123 S.Ct. 456"
    r"(\d+)\s+(S\.?\s?Ct\.)\s+(\d+)",
    # Federal Supplement: e.g., "123 F.Supp.2d 456"
    r"(\d+)\s+(F\.?\s?Supp\.?\s?(?:2d|3d)?)\s+(\d+)",
    # Michigan reporters: e.g., "329 Mich. 683", "68 Mich. App. 272"
    r"(\d+)\s+(Mich\.?\s?(?:App\.?)?)\s+(\d+)",
]

USC_CITATION_PATTERNS = [
    # U.S. Code: "42 U.S.C. § 1983", "18 USC 2251", "18 U.S.C. §§ 2516"
    r"(\d+)\s+U\.?\s*S\.?\s*C\.?\s*(?:A\.?)?\s*(?:§§|§|sections|section|sec\.?)?\s*(\d[\w.\-]*(?:\([^)]+\))*)",
]

# "Title 18, United States Code, Section 2516" and the reverse prose order.
USC_PROSE_PATTERNS = [
    (
        "title-first",
        r"title\s+(\d+)\s*,?\s*(?:of\s+the\s+)?united\s+states\s+code\s*,?\s*(?:section|sec\.?)\s+(\d[\w.\-]*(?:\([^)]+\))*)",
    ),
    (
        "section-first",
        r"(?:section|sec\.?)\s+(\d[\w.\-]*(?:\([^)]+\))*)\s+of\s+title\s+(\d+)\s*,?\s*(?:of\s+the\s+)?united\s+states\s+code",
    ),
]

FEDERAL_RULE_PATTERNS = [
    # Civ., Crim., App., and Bankr. use "P."; Evidence does not.
    r"\b(Fed\.?\s+R\.?\s+(?:(?:Civ|Crim|App|Bankr)\.?\s+P|Evid)\.?\s+\d+(?:\([a-z0-9]+\))*)",
]

CFR_CITATION_PATTERNS = [
    # Code of Federal Regulations: e.g., "40 C.F.R. § 1.1", "21 CFR 314.80"
    r"(\d+)\s+C\.?F\.?R\.?\s+(?:§|section|sec\.?)?\s*(\d+(?:\.[\w-]+)*(?:\([a-z0-9]+\))?)",
]

FEDERAL_REGISTER_PATTERNS = [
    # Federal Register: e.g., "85 FR 12345", "90 Fed. Reg. 54321"
    r"(\d+)\s+(?:FR|Fed\.?\s+Reg\.?|Fed\.?\s+Register|Federal\s+Register)\s+(\d+)",
]

PUBLIC_LAW_PATTERNS = [
    # Public Law: e.g., "Pub. L. 111-148", "P.L. 117-2"
    r"(?:Pub\.?\s+L\.?|P\.L\.)\s+(\d+)-(\d+)",
    # Public Law with "No.": e.g., "Pub. L. No. 117-58", "P.L. No. 117-58"
    r"(?:Pub\.?\s+L\.?|P\.L\.?|Public\s+Law)\s+(?:No\.?\s*)?(\d+)-(\d+)",
]

# Michigan session laws: "1971 PA 196" and "1943 P.A. 184".
# All-caps PA with a four-digit year. "501 Pa 423" stays Pennsylvania Reports.
_PUBLIC_ACT = re.compile(
    r"(?<![A-Za-z0-9])((?:18|19|20)\d{2})\s+(?:PA|P\.A\.)\s+(?:No\.?\s*)?(\d{1,5})(?!\d)"
)

BLUEBOOK_STATE_TO_CODE = {
    "Ala.": "AL",
    "Alaska": "AK",
    "Ariz.": "AZ",
    "Ark.": "AR",
    "Cal.": "CA",
    "Colo.": "CO",
    "Conn.": "CT",
    "Del.": "DE",
    "D.C.": "DC",
    "Fla.": "FL",
    "Florida": "FL",
    "Ga.": "GA",
    "Haw.": "HI",
    "Idaho": "ID",
    "Ill.": "IL",
    "Ind.": "IN",
    "Iowa": "IA",
    "Kan.": "KS",
    "Ky.": "KY",
    "La.": "LA",
    "Mass.": "MA",
    "Md.": "MD",
    "Me.": "ME",
    "Mich.": "MI",
    "Minn.": "MN",
    "Minnesota": "MN",
    "Miss.": "MS",
    "Mo.": "MO",
    "Mont.": "MT",
    "N.C.": "NC",
    "N.D.": "ND",
    "Neb.": "NE",
    "N.H.": "NH",
    "N.J.": "NJ",
    "N.M.": "NM",
    "Nev.": "NV",
    "N.Y.": "NY",
    "Ohio": "OH",
    "Okla.": "OK",
    "Or.": "OR",
    "Pa.": "PA",
    "R.I.": "RI",
    "S.C.": "SC",
    "S.D.": "SD",
    "Tenn.": "TN",
    "Tex.": "TX",
    "Utah": "UT",
    "Va.": "VA",
    "Vt.": "VT",
    "Wash.": "WA",
    "W. Va.": "WV",
    "Wis.": "WI",
    "Wyo.": "WY",
}

_STATE_ABBREV_PATTERN = "|".join(
    sorted((re.escape(value) for value in BLUEBOOK_STATE_TO_CODE), key=len, reverse=True)
)
# Lowercase "me." / "ill." are English words. A real state abbrev starts with a capital.
_LOWERCASE_STATE_WORDS = frozenset({"me", "ill", "or", "la", "pa", "va"})
STATE_STATUTE_PATTERNS = [
    rf"(?P<text>(?P<titled_state>{_STATE_ABBREV_PATTERN})\s+"
    r"(?P<titled_code_name>"
    r"(?:[A-Z][A-Za-z&.\'/-]*\s+){0,5}"
    r"(?:Code(?:\s+Ann\.)?|Stat(?:\.|utes)?(?:\s+Ann\.)?|"
    r"Rev\.\s+Stat\.?(?:\s+Ann\.)?|Gen\.\s+(?:Laws|Stat\.?)(?:\s+Ann\.)?|Comp\.\s+Laws|Cent\.\s+Code)"
    r")\s+tit\.?\s+(?P<titled_title>\d+(?:-[A-Za-z0-9]+)?)\s*,?\s*"
    r"(?:§|sec\.?|section)?\s*(?P<titled_section>\d[\w.:\-]*(?:\([a-z0-9]+\))*))",
    rf"(?P<text>(?P<state>{_STATE_ABBREV_PATTERN})\s+"
    r"(?P<code_name>"
    r"(?:[A-Z][A-Za-z&.\'/-]*\s+){0,5}"
    r"(?:Code(?:\s+Ann\.)?|Stat(?:\.|utes)?(?:\s+Ann\.)?|"
    r"Rev\.\s+Stat\.?(?:\s+Ann\.)?|Gen\.\s+(?:Laws|Stat\.?)(?:\s+Ann\.)?|Comp\.\s+Laws|Cent\.\s+Code|"
    r"Codified\s+Laws|Fam\.\s+Code|Civ\.\s+Code|Penal\s+Code|"
    r"Admin\.\s+Code|Court\s+Rules?|Fam\.\s+Ct\.\s+Act|[A-Z][A-Za-z.\'/-]*\s+Law|"
    r"R\.\s+(?:Civ|Crim|App|Evid|Prof|Jud|Ct|Proc|Gov|Juv|Prob|Adm|Bankr|Sup)\.?(?:\s+[A-Z][A-Za-z.]*){0,3})"
    r")\s*,?\s*(?:§|sec\.?|section)?\s*(?P<section>\d[\w.:\-]*(?:\([a-z0-9]+\))*))",
    r"(?P<text>(?P<state_shorthand>ORS)\s+(?:§|sec\.?|section)?\s*(?P<section_shorthand>\d[\w.:\-]*(?:\([a-z0-9]+\))*))",
    r"(?P<text>(?P<il_title>\d+)\s+ILCS\s+(?P<il_act>\d+)/(?P<il_section>\d[\w.:\-]*(?:\([a-z0-9]+\))*))",
    r"(?P<text>(?P<pa_title>\d+)\s+Pa\.?\s*C\.?S\.?(?:A\.?)?\s+(?:§|sec\.?|section)?\s*(?P<pa_section>\d[\w.:\-]*(?:\([a-z0-9]+\))*))",
    r"(?P<text>\b(?P<mcl>M\.?\s*C\.?\s*L\.?)\s*(?:Ann\.?)?\s*§?\s*(?P<mcl_section>\d+\.\d+[A-Za-z0-9.\-]*))",
    r"(?P<text>\b(?P<rcw>RCW)\s*§?\s*(?P<rcw_section>\d+[A-Za-z]?(?:\.\d+)+))",
    r"(?P<text>\b(?P<ocga>O\.?\s*C\.?\s*G\.?\s*A\.?)\s*§?\s*(?P<ocga_section>\d[\d.\-]*(?:\([a-z0-9]+\))*))",
    r"(?P<text>\b(?P<krs>K\.?\s*R\.?\s*S\.?)\s*§?\s*(?P<krs_section>\d[\d.\-]*(?:\([a-z0-9]+\))*))",
    r"(?P<text>\b(?P<ars>A\.?\s*R\.?\s*S\.?)\s*§?\s*(?P<ars_section>\d[\d.\-]*(?:\([a-z0-9]+\))*))",
    r"(?P<text>\b(?P<nrs>NRS)\s*§?\s*(?P<nrs_section>\d[\d.\-]*(?:\([a-z0-9]+\))*))",
    r"(?P<text>\b(?P<crs>C\.?\s*R\.?\s*S\.?)\s*§?\s*(?P<crs_section>\d[\d.\-]*(?:\([a-z0-9]+\))*))",
    r"(?P<text>\b(?P<njsa>N\.?\s*J\.?\s*S\.?\s*A\.?)\s*§?\s*(?P<njsa_section>\d[\w:.\-]*(?:\([a-z0-9]+\))*))",
    r"(?P<text>(?P<del_title>\d+)\s+Del\.?\s+C\.?\s*§?\s*(?P<del_section>\d[\w.\-]*))",
    r"(?P<text>(?P<mass>Mass\.)\s+Gen\.?\s+Laws(?:\s+Ann\.?)?\s+(?:ch\.?|chapter)\s+(?P<mass_ch>\d+[A-Za-z]?)\s*,?\s*§§?\s*(?P<mass_section>\d[\w.\-]*))",
    r"(?P<text>(?P<md>Md\.)\s+Code(?:\s+Ann\.)?\s*,\s*(?P<md_article>[A-Z][A-Za-z. ]{0,40}?)\s+§§?\s*(?P<md_section>\d[\w.\-]*))",
]


class CitationExtractor:
    """Extract and analyze citations from legal documents."""

    def __init__(self):
        """Initialize citation extractor."""
        self.usc_patterns = [re.compile(p, re.IGNORECASE) for p in USC_CITATION_PATTERNS]
        self.usc_prose_patterns = [
            (kind, re.compile(pattern, re.IGNORECASE)) for kind, pattern in USC_PROSE_PATTERNS
        ]
        self.cfr_patterns = [re.compile(p, re.IGNORECASE) for p in CFR_CITATION_PATTERNS]
        self.fr_patterns = [re.compile(p, re.IGNORECASE) for p in FEDERAL_REGISTER_PATTERNS]
        self.pl_patterns = [re.compile(p, re.IGNORECASE) for p in PUBLIC_LAW_PATTERNS]
        self.rule_patterns = [re.compile(p, re.IGNORECASE) for p in FEDERAL_RULE_PATTERNS]
        self.state_statute_patterns = [re.compile(p, re.IGNORECASE) for p in STATE_STATUTE_PATTERNS]
        self._usc_more = re.compile(
            r"\s*,\s*(?:and\s+|or\s+)?(?:§§?\s*)?(\d[\w.\-]*(?:\([^)]+\))*)",
            re.IGNORECASE,
        )

    def extract_citations(self, text: str) -> List[Citation]:
        """Extract all citations from a text.

        Args:
            text: Text to extract citations from

        Returns:
            List of Citation objects
        """
        citations = []

        # Extract case citations
        citations.extend(self._extract_case_citations(text))

        # Extract USC citations
        citations.extend(self._extract_usc_citations(text))

        # Extract CFR citations
        citations.extend(self._extract_cfr_citations(text))

        # Extract Federal Register citations
        citations.extend(self._extract_fr_citations(text))

        # Extract Public Law citations
        citations.extend(self._extract_pl_citations(text))

        # Extract state statute citations, including Michigan public acts
        citations.extend(self._extract_state_statute_citations(text))
        citations.extend(self._extract_public_act_citations(text))

        # Extract federal rules of procedure and evidence
        citations.extend(self._extract_rule_citations(text))

        # Law journals are not case reporters. "68 Mich. L. Rev. 260" is a journal.
        citations.extend(self._extract_journal_citations(text))

        return _prefer_longer(citations)

    def _extract_case_citations(self, text: str) -> List[Citation]:
        """Extract case law citations."""
        citations = []

        for start, end, volume, reporter, page in iter_case_spans(text):
            citations.append(self._case_citation(text, start, end, volume, reporter, page))
        for start, end, volume, reporter, page in iter_spelled_reporter_spans(text):
            citations.append(
                self._case_citation(text, start, end, volume, reporter, page, text_override=f"{volume} {reporter} {page}")
            )
        for start, end, volume, reporter, page in iter_parallel_reporter_spans(text):
            citations.append(
                self._case_citation(text, start, end, volume, reporter, page, text_override=f"{volume} {reporter} {page}")
            )
        return citations

    def _case_citation(
        self,
        text: str,
        start: int,
        end: int,
        volume: str,
        reporter: str,
        page: str,
        text_override: str | None = None,
    ) -> Citation:
        year_match = re.search(r"\((\d{4})\)", text[end : end + 20])
        citation = Citation(
            type="case",
            text=text_override if text_override is not None else text[start:end],
            reporter=reporter,
            volume=volume,
            page=page,
            year=year_match.group(1) if year_match else None,
            start_pos=start,
            end_pos=end,
        )
        citation.court = self._determine_court(reporter)
        citation.url = self._generate_case_url(citation)
        return citation

    def _extract_journal_citations(self, text: str) -> List[Citation]:
        """Extract law-journal citations. They are not resolved against the case index."""
        citations = []
        for start, end, volume, journal, page in iter_journal_spans(text):
            year_match = re.search(r"\((\d{4})\)", text[end : end + 20])
            citations.append(
                Citation(
                    type="journal",
                    text=text[start:end],
                    reporter=journal,
                    volume=volume,
                    page=page,
                    year=year_match.group(1) if year_match else None,
                    start_pos=start,
                    end_pos=end,
                )
            )
        return citations

    def _usc_citation(self, text: str, title: str, section: str, start: int, end: int) -> Citation:
        section = section.rstrip(".,;:")
        citation = Citation(
            type="usc",
            text=text,
            title=title,
            section=section,
            start_pos=start,
            end_pos=end,
        )
        citation.url = (
            "https://uscode.house.gov/view.xhtml?req=granuleid:"
            f"USC-prelim-title{title}-section{section}"
        )
        return citation

    def _extract_usc_citations(self, text: str) -> List[Citation]:
        """Extract U.S. Code citations, including plural sections and prose forms."""
        citations = []

        for pattern in self.usc_patterns:
            for match in pattern.finditer(text):
                title = match.group(1)
                section = match.group(2).rstrip(".,;:")
                end = match.end() - (len(match.group(2)) - len(section))
                plural = bool(re.search(r"§§|\bsections\b", match.group(0), re.IGNORECASE))
                citations.append(self._usc_citation(text[match.start() : end], title, section, match.start(), end))
                cursor = end
                while True:
                    more = self._usc_more.match(text, cursor)
                    if more is None:
                        break
                    extra = more.group(1).rstrip(".,;:")
                    if not extra:
                        break
                    bare_year = bool(re.fullmatch(r"(?:17|18|19|20)\d{2}", extra))
                    if bare_year and not plural:
                        break
                    extra_end = more.end() - (len(more.group(1)) - len(extra))
                    citations.append(
                        self._usc_citation(
                            f"{title} U.S.C. § {extra}",
                            title,
                            extra,
                            more.start(1),
                            extra_end,
                        )
                    )
                    cursor = extra_end

        for kind, pattern in self.usc_prose_patterns:
            for match in pattern.finditer(text):
                if kind == "title-first":
                    title, section = match.group(1), match.group(2)
                else:
                    section, title = match.group(1), match.group(2)
                section = section.rstrip(".,;:")
                citations.append(
                    self._usc_citation(match.group(0).rstrip(".,;:"), title, section, match.start(), match.end())
                )

        return citations

    def _extract_cfr_citations(self, text: str) -> List[Citation]:
        """Extract Code of Federal Regulations citations."""
        citations = []

        for pattern in self.cfr_patterns:
            for match in pattern.finditer(text):
                title = match.group(1)
                section = match.group(2)

                citation = Citation(
                    type="cfr",
                    text=match.group(0),
                    title=title,
                    section=section,
                    start_pos=match.start(),
                    end_pos=match.end(),
                )

                # Generate URL (eCFR)
                citation.url = f"https://www.ecfr.gov/current/title-{title}/section-{section}"

                citations.append(citation)

        return citations

    def _extract_fr_citations(self, text: str) -> List[Citation]:
        """Extract Federal Register citations."""
        citations = []

        for pattern in self.fr_patterns:
            for match in pattern.finditer(text):
                volume = match.group(1)
                page = match.group(2)

                citation = Citation(
                    type="federal_register",
                    text=match.group(0),
                    volume=volume,
                    page=page,
                    start_pos=match.start(),
                    end_pos=match.end(),
                )

                # Generate URL
                citation.url = f"https://www.federalregister.gov/citation/{volume}-FR-{page}"

                citations.append(citation)

        return citations

    def _extract_rule_citations(self, text: str) -> List[Citation]:
        """Extract federal rules such as Fed. R. Civ. P. 12(b)(6)."""
        citations = []
        for pattern in self.rule_patterns:
            for match in pattern.finditer(text):
                citations.append(
                    Citation(
                        type="rule",
                        text=match.group(1),
                        title=match.group(1),
                        start_pos=match.start(1),
                        end_pos=match.end(1),
                    )
                )
        return citations

    def _extract_pl_citations(self, text: str) -> List[Citation]:
        """Extract Public Law citations."""
        citations = []
        seen_spans = set()

        for pattern in self.pl_patterns:
            for match in pattern.finditer(text):
                if match.span() in seen_spans:
                    continue
                seen_spans.add(match.span())
                congress = match.group(1)
                law = match.group(2)

                citation = Citation(
                    type="public_law",
                    text=match.group(0),
                    volume=congress,  # Store congress number as volume
                    page=law,  # Store law number as page
                    start_pos=match.start(),
                    end_pos=match.end(),
                )

                citation.url = f"https://www.congress.gov/public-law/{congress}th-congress/{law}"

                citations.append(citation)

        return citations

    def _extract_state_statute_citations(self, text: str) -> List[Citation]:
        """Extract Bluebook-style state statute citations."""
        citations = []

        for pattern in self.state_statute_patterns:
            for match in pattern.finditer(text):
                citation_text = match.group("text")
                groupdict = match.groupdict()
                raw_state = groupdict.get("state") or groupdict.get("titled_state") or ""
                if (
                    raw_state[:1].islower()
                    and raw_state.lower().rstrip(".") in _LOWERCASE_STATE_WORDS
                ):
                    continue
                if groupdict.get("mcl"):
                    state_abbrev = "Mich."
                    code_name = "MCL"
                    section = str(match.group("mcl_section") or "")
                elif groupdict.get("rcw"):
                    state_abbrev = "Wash."
                    code_name = "RCW"
                    section = str(match.group("rcw_section") or "")
                elif groupdict.get("ocga"):
                    state_abbrev = "Ga."
                    code_name = "O.C.G.A."
                    section = str(match.group("ocga_section") or "")
                elif groupdict.get("krs"):
                    state_abbrev = "Ky."
                    code_name = "K.R.S."
                    section = str(match.group("krs_section") or "")
                elif groupdict.get("ars"):
                    state_abbrev = "Ariz."
                    code_name = "A.R.S."
                    section = str(match.group("ars_section") or "")
                elif groupdict.get("nrs"):
                    state_abbrev = "Nev."
                    code_name = "NRS"
                    section = str(match.group("nrs_section") or "")
                elif groupdict.get("crs"):
                    state_abbrev = "Colo."
                    code_name = "C.R.S."
                    section = str(match.group("crs_section") or "")
                elif groupdict.get("njsa"):
                    state_abbrev = "N.J."
                    code_name = "N.J.S.A."
                    section = str(match.group("njsa_section") or "")
                elif groupdict.get("del_title"):
                    state_abbrev = "Del."
                    code_name = f"{match.group('del_title')} Del. C."
                    section = str(match.group("del_section") or "")
                elif groupdict.get("mass"):
                    state_abbrev = "Mass."
                    code_name = f"Gen. Laws ch. {match.group('mass_ch')}"
                    section = str(match.group("mass_section") or "")
                elif groupdict.get("md"):
                    state_abbrev = "Md."
                    article = " ".join(str(match.group("md_article") or "").split())
                    code_name = f"Code Ann., {article}" if article else "Code Ann."
                    section = str(match.group("md_section") or "")
                elif groupdict.get("state_shorthand"):
                    state_abbrev = "Or."
                    code_name = str(match.group("state_shorthand") or "").strip()
                    section = str(match.group("section_shorthand") or "")
                elif groupdict.get("il_title"):
                    state_abbrev = "Ill."
                    code_name = f"{match.group('il_title')} ILCS {match.group('il_act')}"
                    section = str(match.group("il_section") or "")
                elif groupdict.get("pa_title"):
                    state_abbrev = "Pa."
                    code_name = f"{match.group('pa_title')} Pa.C.S."
                    section = str(match.group("pa_section") or "")
                elif groupdict.get("titled_state"):
                    state_abbrev = match.group("titled_state")
                    code_name = f"{' '.join(match.group('titled_code_name').split())} tit. {match.group('titled_title')}"
                    section = str(match.group("titled_section") or "")
                else:
                    state_abbrev = match.group("state")
                    code_name = " ".join(match.group("code_name").split())
                    section = match.group("section")
                cleaned_section = section.rstrip(".,;:")
                if cleaned_section != section:
                    citation_text = citation_text[
                        : len(citation_text) - (len(section) - len(cleaned_section))
                    ]
                    section = cleaned_section
                state_code = BLUEBOOK_STATE_TO_CODE.get(state_abbrev)

                citation = Citation(
                    type="state_statute",
                    text=citation_text,
                    title=code_name,
                    section=section,
                    jurisdiction=state_code,
                    start_pos=match.start(),
                    end_pos=match.end(),
                    metadata={
                        "bluebook_state_abbrev": state_abbrev,
                        "code_name": code_name,
                    },
                )
                citations.append(citation)

        return citations

    def _extract_public_act_citations(self, text: str) -> List[Citation]:
        """Extract Michigan public acts printed as ``1971 PA 196``."""
        citations = []
        for match in _PUBLIC_ACT.finditer(text):
            year, number = match.group(1), match.group(2)
            citations.append(
                Citation(
                    type="state_statute",
                    text=match.group(0),
                    title=year,
                    section=number,
                    year=year,
                    jurisdiction="MI",
                    start_pos=match.start(),
                    end_pos=match.end(),
                    metadata={
                        "bluebook_state_abbrev": "Mich.",
                        "code_name": "Public Act",
                    },
                )
            )
        return citations

    def _determine_court(self, reporter: str) -> Optional[str]:
        """Determine court from reporter abbreviation."""
        reporter_lower = reporter.lower().replace(" ", "").replace(".", "").replace("'", "").replace("’", "")

        court_mapping = {
            "us": "U.S. Supreme Court",
            "sct": "U.S. Supreme Court",
            "led": "U.S. Supreme Court",
            "led2d": "U.S. Supreme Court",
            "f3d": "U.S. Court of Appeals",
            "f2d": "U.S. Court of Appeals",
            "f4th": "U.S. Court of Appeals",
            "fappx": "U.S. Court of Appeals (Unpublished)",
            "fsupp": "U.S. District Court",
            "fsupp2d": "U.S. District Court",
            "fsupp3d": "U.S. District Court",
            "mich": "Michigan Supreme Court",
            "michapp": "Michigan Court of Appeals",
        }

        return court_mapping.get(reporter_lower)

    def _generate_case_url(self, citation: Citation) -> Optional[str]:
        """Generate URL for case citation (CourtListener)."""
        if not (citation.volume and citation.reporter and citation.page):
            return None

        # Use CourtListener citation lookup
        reporter_clean = citation.reporter.replace(".", "").replace(" ", "-").lower()
        return f"https://www.courtlistener.com/opinion/{citation.volume}/{reporter_clean}/{citation.page}/"

    def analyze_citations(self, citations: List[Citation]) -> Dict[str, Any]:
        """Analyze extracted citations and generate statistics.

        Args:
            citations: List of Citation objects

        Returns:
            Dict with citation statistics and analysis
        """
        if not citations:
            return {
                "total_citations": 0,
                "by_type": {},
                "unique_citations": 0,
                "citation_density": 0,
            }

        # Count by type
        by_type = {}
        for citation in citations:
            by_type[citation.type] = by_type.get(citation.type, 0) + 1

        # Find unique citations
        unique_texts = set(c.text for c in citations)

        return {
            "total_citations": len(citations),
            "by_type": by_type,
            "unique_citations": len(unique_texts),
            "most_cited": self._find_most_cited(citations),
            "citation_types": list(by_type.keys()),
        }

    def _find_most_cited(self, citations: List[Citation], top_n: int = 5) -> List[Dict[str, Any]]:
        """Find most frequently cited sources."""
        citation_counts = {}

        for citation in citations:
            key = citation.text
            if key not in citation_counts:
                citation_counts[key] = {
                    "text": citation.text,
                    "type": citation.type,
                    "count": 0,
                    "url": citation.url,
                }
            citation_counts[key]["count"] += 1

        # Sort by count
        sorted_citations = sorted(citation_counts.values(), key=lambda x: x["count"], reverse=True)
        return sorted_citations[:top_n]

    def create_citation_graph(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create a citation graph showing relationships between documents.

        Args:
            documents: List of documents with 'id', 'text', and optional 'citations' fields

        Returns:
            Dict with graph structure
        """
        graph = {"nodes": [], "edges": [], "statistics": {}}

        # Create nodes for each document
        for doc in documents:
            graph["nodes"].append(
                {
                    "id": doc.get("id"),
                    "title": doc.get("title", "Unknown"),
                    "type": doc.get("type", "document"),
                }
            )

        # Extract citations and create edges
        for doc in documents:
            doc_id = doc.get("id")
            text = doc.get("text", "")

            citations = self.extract_citations(text)

            for citation in citations:
                # Find matching documents
                for target_doc in documents:
                    if self._citation_matches_document(citation, target_doc):
                        graph["edges"].append(
                            {
                                "source": doc_id,
                                "target": target_doc.get("id"),
                                "citation_text": citation.text,
                                "citation_type": citation.type,
                            }
                        )

        # Calculate statistics
        graph["statistics"] = {
            "total_documents": len(documents),
            "total_edges": len(graph["edges"]),
            "avg_citations_per_document": len(graph["edges"]) / len(documents) if documents else 0,
        }

        return graph

    def _citation_matches_document(self, citation: Citation, document: Dict[str, Any]) -> bool:
        """Check if a citation matches a document."""
        # Simple matching logic - can be enhanced
        doc_title = document.get("title", "").lower()
        citation_text = citation.text.lower()

        # Check if citation text appears in document title
        if citation_text in doc_title:
            return True

        # Check type-specific matches
        if citation.type == "usc" and "us code" in doc_title:
            if citation.title in doc_title:
                return True

        return False


# Convenience functions
def extract_citations_from_text(text: str) -> List[Citation]:
    """Extract all citations from text (convenience function).

    Args:
        text: Text to analyze

    Returns:
        List of Citation objects
    """
    extractor = CitationExtractor()
    return extractor.extract_citations(text)


def analyze_document_citations(text: str) -> Dict[str, Any]:
    """Extract and analyze citations from a document.

    Args:
        text: Document text

    Returns:
        Dict with citations and analysis
    """
    extractor = CitationExtractor()
    citations = extractor.extract_citations(text)
    analysis = extractor.analyze_citations(citations)

    return {
        "citations": [
            {
                "type": c.type,
                "text": c.text,
                "url": c.url,
                "position": {"start": c.start_pos, "end": c.end_pos},
            }
            for c in citations
        ],
        "analysis": analysis,
    }


def create_citation_network(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a citation network from multiple documents.

    Args:
        documents: List of documents with 'id' and 'text' fields

    Returns:
        Dict with network graph structure
    """
    extractor = CitationExtractor()
    return extractor.create_citation_graph(documents)


__all__ = [
    "Citation",
    "CitationExtractor",
    "extract_citations_from_text",
    "analyze_document_citations",
    "create_citation_network",
]
