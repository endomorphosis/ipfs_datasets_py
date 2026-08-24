"""Official Maine Constitution parser.

Generic ARTICLE/Section split of an official local dump.

Local dump: ``MAINE_CONSTITUTION_HTML``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .constitution_split import env_html_path, parse_article_section_html

ME_CONST_URL = "https://legislature.maine.gov/lawlibrary/constitution-of-maine"


def parse_maine_constitution_html(
    html: str,
    *,
    code_name: str = "Maine Constitution",
    max_statutes: Optional[int] = None,
) -> List:
    return parse_article_section_html(
        html,
        state_code="ME",
        state_name="Maine",
        cite_fmt="Me. Const. art. {art}, § {sec}",
        source_url=ME_CONST_URL,
        source_kind="official_maine_constitution_html",
        discovery_method="legislature_maine_gov_constitution",
        code_name=code_name,
        max_statutes=max_statutes,
    )


def configured_constitution_html_path() -> Optional[Path]:
    return env_html_path("MAINE_CONSTITUTION_HTML")
