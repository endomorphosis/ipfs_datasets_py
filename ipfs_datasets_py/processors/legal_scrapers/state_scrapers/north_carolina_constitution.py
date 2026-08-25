"""Official North Carolina Constitution parser.

Generic ARTICLE/Section split of an official local dump. Trailing session-law
cites such as ``(2013-300, s. 1.)`` stay in the section body.

Local dump: ``NORTH_CAROLINA_CONSTITUTION_HTML``. This is not ByChapter
statute HTML and is not archive recovery.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .constitution_split import env_html_path, parse_article_section_html

NC_CONST_URL = "https://www.ncleg.gov/Laws/Constitution/NCConstitution.html"


def parse_north_carolina_constitution_html(
    html: str,
    *,
    code_name: str = "North Carolina Constitution",
    max_statutes: Optional[int] = None,
) -> List:
    return parse_article_section_html(
        html,
        state_code="NC",
        state_name="North Carolina",
        cite_fmt="N.C. Const. art. {art}, § {sec}",
        source_url=NC_CONST_URL,
        source_kind="official_north_carolina_constitution_html",
        discovery_method="ncleg_gov_constitution",
        code_name=code_name,
        max_statutes=max_statutes,
    )


def configured_constitution_html_path() -> Optional[Path]:
    return env_html_path("NORTH_CAROLINA_CONSTITUTION_HTML")
