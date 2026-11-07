"""Reporter abbreviations recognized between a volume and a page.

The names come from the caselaw cite index, plus parallel citations
opinions print beside the official reporter: S. Ct., L. Ed., Cal. Rptr.,
A.L.R., and WL. A single letter is accepted only for A., F., and P.
"""

from __future__ import annotations

import re

REPORTERS: tuple[str, ...] = (
    'Ohio Nisi Prius (n.s.)',
    'Blume Sup. Ct. Trans.',
    'Cal. App. 4th Supp.',
    'Rec. Co. Ch. (S.C.)',
    'Cal. 4th CJP Supp.',
    'Cal. App. 2d Supp.',
    'Cal. App. 3d Supp.',
    'Ill. Cir. Ct. Rep.',
    'N.Y. City Ct. Rep.',
    'Connoly Sur. Rep.',
    'N. Mar. I. Commw.',
    'Super. Ct. (R.I.)',
    'Ohio App. Unrep.',
    'Ohio C.C. (n.s.)',
    'Ohio N.P. (n.s.)',
    'Park. Crim. Rep.',
    'Sarat. Ch. Sent.',
    'Tenn. Crim. App.',
    'U.S. Dist. LEXIS',
    'Cal. App. Supp.',
    "Ct. Int'l Trade",
    'Dev. & Bat. Eq.',
    'How. Pr. (n.s.)',
    'Liquor Tax Rep.',
    'Litt. Sel. Cas.',
    'Lock. Rev. Cas.',
    'Mass. App. Dec.',
    'Mass. App. Div.',
    'U.S. App. LEXIS',
    'Wheel. Cr. Cas.',
    'Conn. Cir. Ct.',
    'Edm. Sel. Cas.',
    'Mass. App. Ct.',
    'Mass. L. Rptr.',
    'Ohio C.C. Dec.',
    'Ohio Cir. Dec.',
    'Pa. D. & C.4th',
    'Pa. D. & C.5th',
    'Pa. Super. Ct.',
    'Tex. Civ. App.',
    'U.S. App. D.C.',
    'Abb. Ct. App.',
    'Balt. C. Rep.',
    'Cal. App. 4th',
    'Cal. App. 5th',
    'Cal. Rptr. 2d',
    'Cal. Rptr. 3d',
    'Colo. L. Rep.',
    'D.C. (patent)',
    'Fla. Supp. 2d',
    'N.Y. St. Rep.',
    'N.Y. Sup. Ct.',
    'Ohio Law Abs.',
    'Ohio Misc. 2d',
    'Pa. D. & C.2d',
    'Pa. D. & C.3d',
    'Serg. & Rawle',
    'Smith (N. H.)',
    'Tex. Ct. App.',
    'Thomp. & Cook',
    'Va. Col. Dec.',
    'Watts & Serg.',
    'Abb. N. Cas.',
    'Cal. App. 2d',
    'Cal. App. 3d',
    'Ill. App. 2d',
    'Ill. App. 3d',
    'Ill. Ct. Cl.',
    'Indian Terr.',
    'Kan. App. 2d',
    'Mart. (n.s.)',
    'Mart. (o.s.)',
    'Ohio App. 2d',
    'Ohio App. 3d',
    'A.K. Marsh.',
    'A.L.R. Fed.',
    'Alaska Fed.',
    'Cal. Unrep.',
    'Cam. & Nor.',
    'Conn. Supp.',
    'Daly (N.Y.)',
    'Dev. & Bat.',
    'F. Supp. 2d',
    'F. Supp. 3d',
    'Hay. & Haz.',
    'Hill & Den.',
    'Johns. Cas.',
    'Mass. Supp.',
    'Mills Surr.',
    'N.J. Super.',
    'Ohio St. 2d',
    'Ohio St. 3d',
    'Okla. Crim.',
    'Pa. D. & C.',
    'Trans. App.',
    'Wash. Terr.',
    'Ariz. App.',
    'Cal. Rptr.',
    'Cole. Cas.',
    'Colo. App.',
    'Conn. App.',
    'E.D. Smith',
    'Fla. Supp.',
    'Freem. Ch.',
    'Johns. Ch.',
    'Jones & S.',
    'McCord Eq.',
    'McMul. Eq.',
    'Mich. App.',
    'Miss. Dec.',
    'N. Mar. I.',
    'N.J. Misc.',
    'N.Y. Crim.',
    'Ohio Misc.',
    'Pa. Commw.',
    'Pa. Super.',
    'Pow. Surr.',
    'Shan. Cas.',
    'Silv. Sup.',
    'Tapp. Rep.',
    'Tenn. App.',
    'Tex. Crim.',
    'U.S. LEXIS',
    'Wash. App.',
    'White & W.',
    'A.L.R.4th',
    'A.L.R.5th',
    'App. D.C.',
    'Ark. App.',
    'Barb. Ch.',
    'Cai. Cas.',
    'Cal. App.',
    'Ct. Cust.',
    'Cust. Ct.',
    'D.C. App.',
    'Fed.Appx.',
    'H. & McH.',
    'Hen. & M.',
    'Hoff. Ch.',
    'Ill. App.',
    'Ind. App.',
    'Ired. Eq.',
    'Jones Eq.',
    'Kan. App.',
    'L. Ed. 2d',
    'Mich. Pr.',
    'N.C. App.',
    'Ohio App.',
    'Ohio C.A.',
    'Ohio C.C.',
    'Ohio L.R.',
    'Ohio N.P.',
    'P.R. Dec.',
    'P.R. Fed.',
    'Paige Ch.',
    'R.I. Dec.',
    'Rich. Eq.',
    'Sand. Ch.',
    'T.B. Mon.',
    'Vet. App.',
    'A.L.R.2d',
    'A.L.R.3d',
    'Abb. Pr.',
    'C.C.P.A.',
    'Cal. 4th',
    'Des. Eq.',
    'E.D. Pa.',
    'Edw. Ch.',
    "F. App'x",
    'F. Supp.',
    'Fed. Cl.',
    'Ga. App.',
    'How. Pr.',
    'La. Ann.',
    'La. App.',
    'Md. App.',
    'Misc. 2d',
    'Misc. 3d',
    'Mo. App.',
    'N.J. Eq.',
    'N.J. Tax',
    'N.Y.S.2d',
    'N.Y.S.3d',
    'Ohio Ch.',
    'Ohio St.',
    'Or. App.',
    'Va. App.',
    'Va. Cas.',
    'Va. Cir.',
    'Wash. 2d',
    'Blackf.',
    'Cal. 2d',
    'Cal. 3d',
    'Cl. Ct.',
    'Ct. Cl.',
    'D. Haw.',
    'F. Cas.',
    'H. & J.',
    'Ill. 2d',
    'Ky. Op.',
    'Md. Ch.',
    'Misc.2d',
    'Misc.3d',
    'Or. Tax',
    'Pennyp.',
    'S. & M.',
    'Utah 2d',
    'Wis. 2d',
    'A.D.2d',
    'A.D.3d',
    'A.L.R.',
    'Alaska',
    'B. Mon',
    'B.T.A.',
    'Brayt.',
    'C.M.A.',
    'Cranch',
    'F.R.D.',
    'Gratt.',
    'Heisk.',
    'Johns.',
    'L. Ed.',
    'Monag.',
    'N.E.2d',
    'N.E.3d',
    'N.J.L.',
    'N.W.2d',
    'N.Y.2d',
    'N.Y.3d',
    'N.Y.S.',
    'S. Ct.',
    'S.E.2d',
    'S.W.2d',
    'S.W.3d',
    'Sandf.',
    'So. 2d',
    'So. 3d',
    'Strob.',
    'T.C.A.',
    'Teiss.',
    'W. Va.',
    'Whart.',
    'Wheat.',
    'Ariz.',
    'Bail.',
    'Barb.',
    'Bosw.',
    'Brad.',
    'Brev.',
    'Busb.',
    'Cold.',
    'Colo.',
    'Conn.',
    'Cush.',
    'Dall.',
    'F.4th',
    'Gilm.',
    'Hilt.',
    'Ired.',
    'Lans.',
    'Litt.',
    'Mass.',
    'Mich.',
    'Minn.',
    'Misc.',
    'Miss.',
    'Mont.',
    'Munf.',
    'Okla.',
    'Pelt.',
    'Pick.',
    'Rand.',
    'Redf.',
    'Rich.',
    'S. Ct',
    'S.Ct.',
    'Scam.',
    'So.3d',
    'Tenn.',
    'Walk.',
    'Wall.',
    'Wash.',
    'Wend.',
    'A.2d',
    'A.3d',
    'A.D.',
    'Aik.',
    'Ark.',
    'B.R.',
    'Cai.',
    'Cal.',
    'Cow.',
    'D.C.',
    'Dev.',
    'F.2d',
    'F.3d',
    'Fla.',
    'Haw.',
    'How.',
    'Hum.',
    'Ill.',
    'Ind.',
    'Iowa',
    'Kan.',
    'M.J.',
    'Met.',
    'Mur.',
    'N.C.',
    'N.D.',
    'N.E.',
    'N.H.',
    'N.J.',
    'N.M.',
    'N.W.',
    'N.Y.',
    'Neb.',
    'Nev.',
    'Ohio',
    'P.2d',
    'P.3d',
    'P.R.',
    'Pet.',
    'Pin.',
    'R.I.',
    'Rob.',
    'S.C.',
    'S.D.',
    'S.E.',
    'S.W.',
    'T.C.',
    'Tex.',
    'Tyl.',
    'U.S.',
    'Utah',
    'V.I.',
    'Wis.',
    'Wyo.',
    'Yer.',
    'Ga.',
    'Ky.',
    'La.',
    'Md.',
    'Me.',
    'Mo.',
    'Or.',
    'Pa.',
    'So.',
    'Va.',
    'Vt.',
    'A.',
    'F.',
    'P.',
    'WL',
    'Sup. Ct.',
    'L. R. A.',
    'Am. St. Rep.',
)

BARE_WORDS = frozenset({'Alaska', 'Cranch', 'Iowa', 'Ohio', 'Utah', 'WL'})
# A bare "12 A 34" is not Atlantic Reporter. The period stays required.
PERIOD_REQUIRED = frozenset({'A.', 'F.', 'P.'})


def _letter(char: str, both: bool) -> str:
    """Match a reporter letter.

    The first letter keeps its capital, so ``or`` is not Oregon and ``Or`` / ``OR``
    are. Later letters match either case, so ``Mich app`` is Michigan Appeals.
    """
    if char.isalpha() and both:
        lower, upper = char.lower(), char.upper()
        if lower != upper:
            return f"[{re.escape(lower)}{re.escape(upper)}]"
    return re.escape(char)


def reporter_pattern(canonical: str) -> str:
    """Regex for one reporter, anchored later by the volume and page.

    Printed periods may be omitted (``46 Mich 107``, ``6 Mich App 153``,
    ``408 NW2d 783``). The page pattern consumes the separator before the
    page, so a trailing period here is ``\\.?`` and does not eat that space.
    The first letter stays capital, matching ``Mich`` and ``MICH``.
    """
    if canonical in BARE_WORDS:
        seen = False
        letters = []
        for char in canonical:
            letters.append(_letter(char, seen))
            seen = seen or char.isalpha()
        return rf"\b{''.join(letters)}\b"
    require_period = canonical in PERIOD_REQUIRED
    parts: list[str] = []
    seen_letter = False
    last = len(canonical) - 1
    for index, char in enumerate(canonical):
        if char == ".":
            if index == last and require_period:
                parts.append(r"\.")
            elif index == last:
                parts.append(r"\.?")
            else:
                parts.append(r"\.?\s*")
        elif char == " ":
            parts.append(r"\s*")
        elif char in {"'", "’"}:
            parts.append(r"['’]?")
        elif char == "(":
            parts.append(r"\(\s*")
        elif char == ")":
            parts.append(r"\s*\)")
        elif char == "&":
            parts.append("&")
        else:
            parts.append(_letter(char, seen_letter))
            seen_letter = seen_letter or char.isalpha()
    return "".join(parts)


def _compile() -> dict[str, re.Pattern[str]]:
    grouped: dict[str, list[str]] = {}
    ordered = sorted(REPORTERS, key=lambda item: (-len(item), item))
    for canonical in ordered:
        grouped.setdefault(canonical[0].upper(), []).append(reporter_pattern(canonical))
    compiled: dict[str, re.Pattern[str]] = {}
    # [N. S.] / (N.S.) is the new-series marker printed before the page.
    # A pinpoint letter may follow the page (402 Mich 950j). 2d/3d/4th/5th
    # stay series markers, not pages.
    page = (
        r"(?:\s*[\[(]\s*N\.?\s*S\.?\s*[\])])?(?:\s*,\s*|\s+)"
        r"(?!(?i:2d|3d|4th|5th)\b)(\d{1,8})(?!\d)"
    )
    for initial, alts in grouped.items():
        compiled[initial] = re.compile(
            rf"({'|'.join(alts)})(?!\w){page}",
        )
    return compiled


CASE_PATTERNS = _compile()

VOLUME = re.compile(r"(?<![A-Za-z0-9])(\d{1,4})\s+(?=[A-Za-z])")


def _is_public_act(volume: str, reporter: str) -> bool:
    """``1943 PA 184`` is a public act, not Pennsylvania Reports."""
    if "." in reporter or any(char.islower() for char in reporter):
        return False
    letters = "".join(char for char in reporter if char.isalpha())
    return letters == "PA" and len(volume) == 4 and volume[:2] in {"18", "19", "20"}


def iter_case_spans(text: str):
    """Yield volume, reporter, and page spans. The reporter must be in REPORTERS."""
    emitted = 0
    for volume in VOLUME.finditer(text):
        if volume.start() < emitted:
            continue
        at = volume.end()
        if at >= len(text) or not text[at].isalpha():
            continue
        pattern = CASE_PATTERNS.get(text[at].upper())
        if pattern is None:
            continue
        found = pattern.match(text, at)
        if found is None:
            continue
        reporter = found.group(1)
        if _is_public_act(volume.group(1), reporter):
            continue
        yield volume.start(), found.end(), volume.group(1), reporter, found.group(2)
        emitted = found.end()

