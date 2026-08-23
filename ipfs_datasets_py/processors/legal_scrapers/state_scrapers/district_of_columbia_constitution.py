"""Official District of Columbia Home Rule Charter parser.

The District has a Home Rule Charter rather than a state constitution.
Generic ARTICLE/Section split of an official local dump.

Local dump: ``DISTRICT_OF_COLUMBIA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .constitution_split import env_html_path, parse_article_section_html

DC_CHARTER_URL = "https://code.dccouncil.gov/us/dc/council/code/titles/1/chapters/2"


def parse_district_of_columbia_constitution_html(
    html: str,
    *,
    code_name: str = "District of Columbia Home Rule Charter",
    max_statutes: Optional[int] = None,
) -> List:
    return parse_article_section_html(
        html,
        state_code="DC",
        state_name="District of Columbia",
        cite_fmt="D.C. Charter art. {art}, § {sec}",
        source_url=DC_CHARTER_URL,
        source_kind="official_district_of_columbia_charter_html",
        discovery_method="dccouncil_home_rule_charter",
        code_name=code_name,
        max_statutes=max_statutes,
    )


def configured_constitution_html_path() -> Optional[Path]:
    return env_html_path("DISTRICT_OF_COLUMBIA_CONSTITUTION_HTML")
