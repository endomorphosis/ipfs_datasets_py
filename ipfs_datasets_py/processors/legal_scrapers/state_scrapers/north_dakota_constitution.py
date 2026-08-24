"""Official North Dakota Constitution parser.

Generic ARTICLE/Section split of an official local dump.

Local dump: ``NORTH_DAKOTA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .constitution_split import env_html_path, parse_article_section_html

ND_CONST_URL = "https://ndlegis.gov/constitution"


def parse_north_dakota_constitution_html(
    html: str,
    *,
    code_name: str = "North Dakota Constitution",
    max_statutes: Optional[int] = None,
) -> List:
    return parse_article_section_html(
        html,
        state_code="ND",
        state_name="North Dakota",
        cite_fmt="N.D. Const. art. {art}, § {sec}",
        source_url=ND_CONST_URL,
        source_kind="official_north_dakota_constitution_html",
        discovery_method="ndlegis_gov_constitution",
        code_name=code_name,
        max_statutes=max_statutes,
    )


def configured_constitution_html_path() -> Optional[Path]:
    return env_html_path("NORTH_DAKOTA_CONSTITUTION_HTML")
