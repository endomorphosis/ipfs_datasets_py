"""Official South Carolina Constitution parser.

Generic ARTICLE/Section split of an official local dump.

Local dump: ``SOUTH_CAROLINA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .constitution_split import env_html_path, parse_article_section_html

SC_CONST_URL = "https://www.scstatehouse.gov/scconstitution/scconst.php"


def parse_south_carolina_constitution_html(
    html: str,
    *,
    code_name: str = "South Carolina Constitution",
    max_statutes: Optional[int] = None,
) -> List:
    return parse_article_section_html(
        html,
        state_code="SC",
        state_name="South Carolina",
        cite_fmt="S.C. Const. art. {art}, § {sec}",
        source_url=SC_CONST_URL,
        source_kind="official_south_carolina_constitution_html",
        discovery_method="scstatehouse_gov_constitution",
        code_name=code_name,
        max_statutes=max_statutes,
    )


def configured_constitution_html_path() -> Optional[Path]:
    return env_html_path("SOUTH_CAROLINA_CONSTITUTION_HTML")
