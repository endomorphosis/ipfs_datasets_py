"""Official Iowa Constitution parser.

Generic ARTICLE/Section split of an official local dump.

Local dump: ``IOWA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .constitution_split import env_html_path, parse_article_section_html

IA_CONST_URL = "https://www.legis.iowa.gov/law/constitution"


def parse_iowa_constitution_html(
    html: str,
    *,
    code_name: str = "Iowa Constitution",
    max_statutes: Optional[int] = None,
) -> List:
    return parse_article_section_html(
        html,
        state_code="IA",
        state_name="Iowa",
        cite_fmt="Iowa Const. art. {art}, § {sec}",
        source_url=IA_CONST_URL,
        source_kind="official_iowa_constitution_html",
        discovery_method="legis_iowa_gov_constitution",
        code_name=code_name,
        max_statutes=max_statutes,
    )


def configured_constitution_html_path() -> Optional[Path]:
    return env_html_path("IOWA_CONSTITUTION_HTML")
