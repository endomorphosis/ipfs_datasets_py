"""Exact Louisiana Law.aspx parser/frontier reconciliation tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import louisiana_law
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    StateLawPageMultiFetchResult,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana import (
    LouisianaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.louisiana_law import (
    source_bound_terminal_disposition_from_law_html,
    terminal_disposition_from_law_html,
)


def _receipt(url: str, payload: bytes) -> dict[str, str]:
    return {
        "official_url": url,
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "source_transport": "direct",
    }


def _batch_result(
    requested: list[str],
    payload_by_url: dict[str, bytes],
    *,
    receipts: bool = True,
) -> StateLawPageMultiFetchResult:
    payloads = [payload_by_url[url] for url in requested]
    return StateLawPageMultiFetchResult(
        urls=list(requested),
        payloads=payloads,
        errors=[None] * len(requested),
        transport_receipts=(
            [_receipt(url, payload) for url, payload in zip(requested, payloads)]
            if receipts
            else [None] * len(requested)
        ),
        parser_input_envelopes=[None] * len(requested),
        stats={
            "direct_initial_successes": len(requested),
            "common_crawl": {
                "range_fetch_calls": 0,
                "naive_range_fetches": 0,
                "range_fetches_avoided": 0,
            },
        },
    )


def _operative_dot_label_html() -> str:
    return """
    <form id="aspnetForm" name="aspnetForm" method="post"
          action="./Law.aspx?d=1238853">
      <input type="submit" name="ctl00$PageBody$ButtonPrevious"
             value=" &lt; " id="ctl00_PageBody_ButtonPrevious"
             title="view previous" />
      <span id="ctl00_PageBody_LabelName" class="title"
            style="font-size:Large;">RS 32.1270.41</span>
      <input type="submit" name="ctl00$PageBody$ButtonNext"
             value=" &gt; " id="ctl00_PageBody_ButtonNext"
             title="view next" />
      <a id="ctl00_PageBody_linkPrint" title="Printable Version"
         href="LawPrint.aspx?d=1238853" target="_blank">Print</a>
      <input type="hidden" id="ctl00_PageBody_HiddenDocId" value="1238853" />
      <span id="ctl00_PageBody_LabelDocument"><div id="WPMainDoc">
        <p style="text-align:left; text-indent: -0.5in; margin-left: 0.5in">
          &sect;1270.41.  Exclusiveness
        </p>
        <p style="text-align:left">
          This Part provides exclusive remedies, warranties, and peremptive
          periods as between the manufacturer, dealer, and consumer, relative
          to nonconformity defects as defined in this Part, and no other
          provisions of law relative to recreational vehicle warranties and
          redhibitory vices and defects shall apply. Nothing herein shall be
          construed to affect or limit any warranty of title.
        </p>
        <p style="text-align:left">Acts 2021, No. 220, &sect;1.</p>
      </div></span>
    </form>
    """


def _empty_official_locator_html(
    *,
    label: str = "RS 13:2589.1",
    document_id: str = "763423",
    form_action: str = "./Law.aspx?d=763423",
    print_href: str = "LawPrint.aspx?d=763423",
    document: str = "",
) -> str:
    return f"""
    <form id="aspnetForm" action="{form_action}">
      <input id="ctl00_PageBody_ButtonPrevious" />
      <span id="ctl00_PageBody_LabelName">{label}</span>
      <input id="ctl00_PageBody_ButtonNext" />
      <a id="ctl00_PageBody_linkPrint" href="{print_href}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _malformed_blank_official_locator_html(
    *,
    label: str = "RS 13:5556",
    document_id: str = "781433",
    form_action: str = "./Law.aspx?d=781433",
    print_href: str = "LawPrint.aspx?d=781433",
    document: str = "<p class=\"A0001\">&sect;5556. [Blank)]</p>",
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    previous = (
        '<input id="ctl00_PageBody_ButtonPrevious" />' if include_previous else ""
    )
    next_button = '<input id="ctl00_PageBody_ButtonNext" />' if include_next else ""
    return f"""
    <form id="aspnetForm" action="{form_action}">
      {previous}
      <span id="ctl00_PageBody_LabelName">{label}</span>
      {next_button}
      <a id="ctl00_PageBody_linkPrint" href="{print_href}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _blank_range_cross_reference_html(
    *,
    label: str = "RS 33:130.431",
    document_id: str = "88919",
    form_action: str = "./Law.aspx?d=88919",
    print_href: str = "LawPrint.aspx?d=88919",
    document: str = (
        '<p align="center" class="A0001">SUBPART B-19. FOURTEENTH AND '
        "SIXTEENTH WARDS</p>"
        '<p align="center" class="A0001">NEIGHBORHOOD DEVELOPMENT DISTRICT</p>'
        '<p align="justify" class="A0002">&sect;130.431. '
        "&sect;&sect;130.431-130.436 Blank. See R.S. 33:9083.</p>"
    ),
) -> str:
    return f"""
    <form id="aspnetForm" name="aspnetForm" method="post"
          action="{form_action}">
      <input type="submit" name="ctl00$PageBody$ButtonPrevious"
             value=" &lt; " id="ctl00_PageBody_ButtonPrevious"
             title="view previous" />
      <span id="ctl00_PageBody_LabelName" class="title"
            style="font-size:Large;">{label}</span>
      <input type="submit" name="ctl00$PageBody$ButtonNext"
             value=" &gt; " id="ctl00_PageBody_ButtonNext"
             title="view next" />
      <a id="ctl00_PageBody_linkPrint" title="Printable Version"
         href="{print_href}" target="_blank">Print</a>
      <input type="hidden" name="ctl00$PageBody$HiddenDocId"
             id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _act_section_suffix_redesignation_html(
    *,
    label: str = "RS 14:32.9",
    document_id: str = "78416",
    form_action: str = "./Law.aspx?d=78416",
    print_href: str = "LawPrint.aspx?d=78416",
    document: str = (
        "<p>&sect;32.9. Redesignated as R.S. 14:87.10 by Acts 2022, "
        "No. 545, &sect;6A.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    previous = (
        '<input id="ctl00_PageBody_ButtonPrevious" />' if include_previous else ""
    )
    next_button = '<input id="ctl00_PageBody_ButtonNext" />' if include_next else ""
    return f"""
    <form id="aspnetForm" action="{form_action}">
      {previous}
      <span id="ctl00_PageBody_LabelName">{label}</span>
      {next_button}
      <a id="ctl00_PageBody_linkPrint" href="{print_href}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _chapter_wrapped_redesignation_html(
    *,
    label: str = "RS 33:1421",
    document_id: str = "89224",
    form_action: str = "./Law.aspx?d=89224",
    form_method: str = "post",
    form_name: str = "aspnetForm",
    print_href: str = "LawPrint.aspx?d=89224",
    print_target: str = "_blank",
    print_title: str = "Printable Version",
    document: str = (
        '<p class="A0001"><br /></p>'
        '<p class="A0001"><br /></p>'
        '<p class="A0002" align="center">CHAPTER 3. PUBLIC OFFICERS</p>'
        '<p class="A0002" align="center">'
        "(REDESIGNATED AS CHAPTER 35 OF TITLE 13)</p>"
        '<p class="A0002" align="justify">&sect;1421. Redesignated as '
        "R.S. 13:5521 pursuant to Acts 2011, No. 248, &sect;3.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    previous = (
        '<input type="submit" name="ctl00$PageBody$ButtonPrevious" '
        'value=" &lt; " id="ctl00_PageBody_ButtonPrevious" '
        'title="view previous" />'
        if include_previous
        else ""
    )
    next_button = (
        '<input type="submit" name="ctl00$PageBody$ButtonNext" '
        'value=" &gt; " id="ctl00_PageBody_ButtonNext" title="view next" />'
        if include_next
        else ""
    )
    return f"""
    <form id="aspnetForm" name="{form_name}" method="{form_method}"
          action="{form_action}">
      {previous}
      <span id="ctl00_PageBody_LabelName" class="title"
            style="font-size:Large;">{label}</span>
      {next_button}
      <a id="ctl00_PageBody_linkPrint" title="{print_title}"
         href="{print_href}" target="{print_target}">Print</a>
      <input type="hidden" name="ctl00$PageBody$HiddenDocId"
             id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _article_reserved_html(
    *,
    label: str = "RS 29:104",
    label_class: str = "title",
    label_style: str = "font-size:Large;",
    document_id: str = "85324",
    form_action: str = "./Law.aspx?d=85324",
    form_method: str = "post",
    form_name: str = "aspnetForm",
    print_href: str = "LawPrint.aspx?d=85324",
    print_target: str = "_blank",
    print_title: str = "Printable Version",
    document: str = (
        '<p align="justify" class="A0001">'
        "&sect;104. &nbsp;Article 4. &nbsp;[Reserved] "
        "</p>"
    ),
    previous_name: str = "ctl00$PageBody$ButtonPrevious",
    previous_title: str = "view previous",
    previous_type: str = "submit",
    previous_value: str = " &lt; ",
    next_name: str = "ctl00$PageBody$ButtonNext",
    next_title: str = "view next",
    next_type: str = "submit",
    next_value: str = " &gt; ",
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    previous = ""
    if include_previous:
        previous = (
            '<input id="ctl00_PageBody_ButtonPrevious" '
            f'name="{previous_name}" title="{previous_title}" '
            f'type="{previous_type}" value="{previous_value}" />'
        )
    next_button = ""
    if include_next:
        next_button = (
            '<input id="ctl00_PageBody_ButtonNext" '
            f'name="{next_name}" title="{next_title}" '
            f'type="{next_type}" value="{next_value}" />'
        )
    return f"""
    <form id="aspnetForm" name="{form_name}" method="{form_method}"
          action="{form_action}">
      {previous}
      <span id="ctl00_PageBody_LabelName" class="{label_class}"
            style="{label_style}">{label}</span>
      {next_button}
      <a id="ctl00_PageBody_linkPrint" href="{print_href}"
         target="{print_target}" title="{print_title}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _article_12_reserved_html(**overrides: str | bool) -> str:
    values: dict[str, str | bool] = {
        "label": "RS 29:112",
        "document_id": "85333",
        "form_action": "./Law.aspx?d=85333",
        "print_href": "LawPrint.aspx?d=85333",
        "document": (
            '<p align="justify" class="A0001">'
            "&sect;112. &nbsp;Article 12. &nbsp;[Reserved] "
            "</p>"
        ),
    }
    values.update(overrides)
    return _article_reserved_html(**values)  # type: ignore[arg-type]


def _article_68_reserved_html(**overrides: str | bool) -> str:
    values: dict[str, str | bool] = {
        "label": "RS 29:168",
        "document_id": "85397",
        "form_action": "./Law.aspx?d=85397",
        "print_href": "LawPrint.aspx?d=85397",
        "document": (
            '<p align="justify" class="A0001">'
            "&sect;168. &nbsp;Article 68. &nbsp;[Reserved] "
            "</p>"
        ),
    }
    values.update(overrides)
    return _article_reserved_html(**values)  # type: ignore[arg-type]


def _article_69_reserved_html(**overrides: str | bool) -> str:
    values: dict[str, str | bool] = {
        "label": "RS 29:169",
        "document_id": "85398",
        "form_action": "./Law.aspx?d=85398",
        "print_href": "LawPrint.aspx?d=85398",
        "document": (
            '<p align="justify" class="A0001">'
            "&sect;169. &nbsp;Article 69. &nbsp;[Reserved] "
            "</p>"
        ),
    }
    values.update(overrides)
    return _article_reserved_html(**values)  # type: ignore[arg-type]


def _article_106_reserved_html(**overrides: str | bool) -> str:
    values: dict[str, str | bool] = {
        "label": "RS 29:206",
        "document_id": "85440",
        "form_action": "./Law.aspx?d=85440",
        "print_href": "LawPrint.aspx?d=85440",
        "document": (
            '<p align="justify" class="A0001">'
            "&sect;206. &nbsp;Article 106. &nbsp;[Reserved] "
            "</p>"
        ),
    }
    values.update(overrides)
    return _article_reserved_html(**values)  # type: ignore[arg-type]


_ADDITIONAL_ARTICLE_RESERVED_CASES = (
    ("85450", "RS 29:213", "213", "113"),
    ("85455", "RS 29:218", "218", "118"),
    ("85456", "RS 29:219", "219", "119"),
    ("85460", "RS 29:222", "222", "122"),
    ("85463", "RS 29:225", "225", "125"),
    ("85464", "RS 29:226", "226", "126"),
    ("85465", "RS 29:227", "227", "127"),
    ("85467", "RS 29:229", "229", "129"),
)


def _parenthesized_reserved_html(
    *,
    label: str = "RS 15:171",
    document_id: str = "78995",
    form_action: str = "./Law.aspx?d=78995",
    print_href: str = "LawPrint.aspx?d=78995",
    document: str = "<p>&sect;171. (Reserved).</p>",
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    previous = (
        '<input id="ctl00_PageBody_ButtonPrevious" />' if include_previous else ""
    )
    next_button = '<input id="ctl00_PageBody_ButtonNext" />' if include_next else ""
    return f"""
    <form id="aspnetForm" action="{form_action}">
      {previous}
      <span id="ctl00_PageBody_LabelName">{label}</span>
      {next_button}
      <a id="ctl00_PageBody_linkPrint" href="{print_href}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _omitted_as_obsolete_html(
    *,
    label: str = "RS 16:83",
    document_id: str = "79701",
    form_action: str = "./Law.aspx?d=79701",
    print_href: str = "LawPrint.aspx?d=79701",
    document: str = "<p>&sect;83. Omitted as obsolete</p>",
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    previous = (
        '<input id="ctl00_PageBody_ButtonPrevious" />' if include_previous else ""
    )
    next_button = '<input id="ctl00_PageBody_ButtonNext" />' if include_next else ""
    return f"""
    <form id="aspnetForm" action="{form_action}">
      {previous}
      <span id="ctl00_PageBody_LabelName">{label}</span>
      {next_button}
      <a id="ctl00_PageBody_linkPrint" href="{print_href}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _dated_termination_html(
    *,
    label: str = "RS 17:85.9",
    document_id: str = "285631",
    form_action: str = "./Law.aspx?d=285631",
    print_href: str = "LawPrint.aspx?d=285631",
    document: str = (
        "<p>&sect;85.9. Terminated on Dec. 31, 2004, by Acts 2004, No. 563, "
        "&sect;3, eff. July 6, 2004.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    previous = (
        '<input id="ctl00_PageBody_ButtonPrevious" />' if include_previous else ""
    )
    next_button = '<input id="ctl00_PageBody_ButtonNext" />' if include_next else ""
    return f"""
    <form id="aspnetForm" action="{form_action}">
      {previous}
      <span id="ctl00_PageBody_LabelName">{label}</span>
      {next_button}
      <a id="ctl00_PageBody_linkPrint" href="{print_href}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _dated_null_and_void_html(**overrides: str | bool) -> str:
    values: dict[str, str | bool] = {
        "label": "RS 30:2014.6",
        "document_id": "410448",
        "form_action": "./Law.aspx?d=410448",
        "print_href": "LawPrint.aspx?d=410448",
        "document": (
            '<p align="justify" class="A0001">'
            "&sect;2014.6. &nbsp;Null and void as of Jan. 1, 2009. &nbsp;"
            "See Acts 2006, No. 779, &sect;3.</p>"
        ),
    }
    values.update(overrides)
    return _article_reserved_html(**values)  # type: ignore[arg-type]


def _dated_termination_85_10_html(
    *,
    label: str = "RS 17:85.10",
    document_id: str = "285632",
    form_action: str = "./Law.aspx?d=285632",
    print_href: str = "LawPrint.aspx?d=285632",
    document: str = (
        "<p>&sect;85.10. Terminated on Dec. 31, 2004, by Acts 2004, No. 718, "
        "&sect;3, eff. July 6, 2004.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    return _dated_termination_html(
        label=label,
        document_id=document_id,
        form_action=form_action,
        print_href=print_href,
        document=document,
        include_previous=include_previous,
        include_next=include_next,
    )


def _dated_termination_23_1020_html(
    *,
    label: str = "RS 23:1020",
    document_id: str = "409787",
    form_action: str = "./Law.aspx?d=409787",
    print_href: str = "LawPrint.aspx?d=409787",
    document: str = (
        "<p>CHAPTER 10. WORKERS' COMPENSATION</p>"
        "<p>PART I. SCOPE AND OPERATION</p>"
        "<p>SUBPART A. DEFINITIONS</p>"
        "<p>&sect;1020. Terminated on June 30, 2006, by Acts 2006, No. 193, "
        "eff. June 2, 2006.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    previous = (
        '<input id="ctl00_PageBody_ButtonPrevious" />' if include_previous else ""
    )
    next_button = '<input id="ctl00_PageBody_ButtonNext" />' if include_next else ""
    return f"""
    <form id="aspnetForm" action="{form_action}">
      {previous}
      <span id="ctl00_PageBody_LabelName">{label}</span>
      {next_button}
      <a id="ctl00_PageBody_linkPrint" href="{print_href}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _wrapped_title_25_heading_html(
    *,
    label: str = "RS 25",
    document_id: str = "84265",
    form_action: str = "./Law.aspx?d=84265",
    form_method: str = "post",
    print_href: str = "LawPrint.aspx?d=84265",
    print_target: str = "_blank",
    print_title: str = "Printable Version",
    document: str = (
        '<p class="A0001" align="justify">TITLE 25. &nbsp;LIBRARIES, '
        "MUSEUMS, AND OTHER SCIENTIFIC </p>"
        '<p class="A0001" align="justify">AND CULTURAL FACILITIES </p>'
    ),
    previous_name: str = "ctl00$PageBody$ButtonPrevious",
    previous_title: str = "view previous",
    previous_type: str = "submit",
    previous_value: str = " &lt; ",
    next_name: str = "ctl00$PageBody$ButtonNext",
    next_title: str = "view next",
    next_type: str = "submit",
    next_value: str = " &gt; ",
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    previous = (
        '<input id="ctl00_PageBody_ButtonPrevious" '
        f'name="{previous_name}" title="{previous_title}" '
        f'type="{previous_type}" value="{previous_value}" />'
        if include_previous
        else ""
    )
    next_button = (
        '<input id="ctl00_PageBody_ButtonNext" '
        f'name="{next_name}" title="{next_title}" '
        f'type="{next_type}" value="{next_value}" />'
        if include_next
        else ""
    )
    return f"""
    <form id="aspnetForm" action="{form_action}" method="{form_method}">
      {previous}
      <span id="ctl00_PageBody_LabelName">{label}</span>
      {next_button}
      <a id="ctl00_PageBody_linkPrint" href="{print_href}"
         target="{print_target}" title="{print_title}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _range_redesignation_html(
    *,
    label: str = "RS 17:771",
    document_id: str = "81194",
    form_action: str = "./Law.aspx?d=81194",
    print_href: str = "LawPrint.aspx?d=81194",
    document: str = (
        "<p>PART VII. OPTIONAL RETIREMENT PLAN FOR ACADEMIC</p>"
        "<p>AND ADMINISTRATIVE EMPLOYEES OF PUBLIC</p>"
        "<p>INSTITUTIONS OF HIGHER EDUCATION</p>"
        "<p>&sect;771. &sect;&sect;771 to 781 redesignated as R.S. 11:921 to "
        "931 by Acts 1991, No. 74, &sect;3.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    previous = (
        '<input id="ctl00_PageBody_ButtonPrevious" />' if include_previous else ""
    )
    next_button = '<input id="ctl00_PageBody_ButtonNext" />' if include_next else ""
    return f"""
    <form id="aspnetForm" action="{form_action}">
      {previous}
      <span id="ctl00_PageBody_LabelName">{label}</span>
      {next_button}
      <a id="ctl00_PageBody_linkPrint" href="{print_href}">Print</a>
      <input id="ctl00_PageBody_HiddenDocId" value="{document_id}" />
      <span id="ctl00_PageBody_LabelDocument">{document}</span>
    </form>
    """


def _range_redesignation_17_881_html(
    *,
    label: str = "RS 17:881",
    document_id: str = "81224",
    form_action: str = "./Law.aspx?d=81224",
    print_href: str = "LawPrint.aspx?d=81224",
    document: str = (
        "<p>PART VIII. STATE-SCHOOL EMPLOYEES RETIREMENT SYSTEM</p>"
        "<p>&sect;881. &sect;&sect;881 to 994 redesignated as R.S. 11:1001 to "
        "1204 by Acts 1991, No. 74, &sect;3.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    return _range_redesignation_html(
        label=label,
        document_id=document_id,
        form_action=form_action,
        print_href=print_href,
        document=document,
        include_previous=include_previous,
        include_next=include_next,
    )


def _range_redesignation_17_1011_html(
    *,
    label: str = "RS 17:1011",
    document_id: str = "79745",
    form_action: str = "./Law.aspx?d=79745",
    print_href: str = "LawPrint.aspx?d=79745",
    document: str = (
        "<p>PART IX. ORLEANS PARISH SCHOOL EMPLOYEES</p>"
        "<p>RETIREMENT SYSTEM</p>"
        "<p>SUBPART A. GENERAL PROVISIONS</p>"
        "<p>&sect;1011-1128. Redesignated as R.S. 11:951.1-951.88 pursuant "
        "to R.S. 24:253.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    return _range_redesignation_html(
        label=label,
        document_id=document_id,
        form_action=form_action,
        print_href=print_href,
        document=document,
        include_previous=include_previous,
        include_next=include_next,
    )


def _range_redesignation_18_1651_html(
    *,
    label: str = "RS 18:1651",
    document_id: str = "81494",
    form_action: str = "./Law.aspx?d=81494",
    print_href: str = "LawPrint.aspx?d=81494",
    document: str = (
        "<p>CHAPTER 12. &nbsp;REGISTRARS OF VOTERS</p>"
        "<p>EMPLOYEES' RETIREMENT SYSTEM</p>"
        "<p>&sect;1651. &nbsp;&sect;&sect;1651 to 1844 redesignated by Acts "
        "1991, No. 74, &sect;3. &nbsp;See, now, Title 11.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    return _range_redesignation_html(
        label=label,
        document_id=document_id,
        form_action=form_action,
        print_href=print_href,
        document=document,
        include_previous=include_previous,
        include_next=include_next,
    )


def _range_redesignation_29_461_html(**overrides: str | bool) -> str:
    values: dict[str, str | bool] = {
        "label": "RS 29:461",
        "document_id": "85614",
        "form_action": "./Law.aspx?d=85614",
        "print_href": "LawPrint.aspx?d=85614",
        "document": (
            '<p align="center" class="A0001">PART II. &nbsp;PENSIONS</p>'
            '<p align="justify" class="A0002">&sect;461. &nbsp;'
            "&sect;&sect;461 to 468 Redesignated as R.S. 11:1391 to 1397 "
            "by Acts 1991, No. 74, &sect;1.</p>"
        ),
    }
    values.update(overrides)
    return _article_reserved_html(**values)  # type: ignore[arg-type]


def _range_redesignation_30_1051_html(**overrides: str | bool) -> str:
    values: dict[str, str | bool] = {
        "label": "RS 30:1051",
        "document_id": "86914",
        "form_action": "./Law.aspx?d=86914",
        "print_href": "LawPrint.aspx?d=86914",
        "document": (
            '<p align="center" class="A0001">CHAPTER 11. '
            "&nbsp;ENVIRONMENTAL QUALITY</p>"
            '<p align="justify" class="A0002">&sect;1051. &nbsp;'
            "&sect;&sect;1051 to 1150 .96 redesignated as Subtitle II of "
            "Title 30 (R.S. 30:2001 to 2396)</p>"
        ),
    }
    values.update(overrides)
    return _article_reserved_html(**values)  # type: ignore[arg-type]


def _to_redesignation_18_221_html(
    *,
    label: str = "RS 18:221",
    document_id: str = "81535",
    form_action: str = "./Law.aspx?d=81535",
    print_href: str = "LawPrint.aspx?d=81535",
    document: str = (
        "<p>&sect;221. Redesignated to R.S. 18:66 by Acts 2017, No. 176, "
        "&sect;6, eff. June 14, 2017.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    return _range_redesignation_html(
        label=label,
        document_id=document_id,
        form_action=form_action,
        print_href=print_href,
        document=document,
        include_previous=include_previous,
        include_next=include_next,
    )


def _title_30_to_redesignation_html(
    *,
    document_id: str,
    from_section: str,
    to_section: str,
    element_name: str,
    document: str | None = None,
    **overrides: str | bool,
) -> str:
    text = (
        f"&sect;{from_section}. Redesignated to R.S. 17:{to_section} by "
        "Acts 2020, No. 317."
    )
    if document is None:
        if element_name == "div":
            document = f'<div id="WPMainDoc">{text}</div>'
        else:
            document = (
                '<p style="text-align:left; text-indent: -0.5in; '
                f'margin-left: 0.5in">{text}</p>'
            )
    values: dict[str, str | bool] = {
        "label": f"RS 30:{from_section}",
        "document_id": document_id,
        "form_action": f"./Law.aspx?d={document_id}",
        "print_href": f"LawPrint.aspx?d={document_id}",
        "document": document,
    }
    values.update(overrides)
    return _article_reserved_html(**values)  # type: ignore[arg-type]


def _effective_date_redesignation_22_2_1_html(
    *,
    label: str = "RS 22:2.1",
    document_id: str = "506659",
    form_action: str = "./Law.aspx?d=506659",
    print_href: str = "LawPrint.aspx?d=506659",
    document: str = (
        "<p>&sect;2.1. &nbsp;Redesignated as R.S. 22:42 by Acts 2008, "
        "No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    return _range_redesignation_html(
        label=label,
        document_id=document_id,
        form_action=form_action,
        print_href=print_href,
        document=document,
        include_previous=include_previous,
        include_next=include_next,
    )


def _effective_date_redesignation_22_4_html(
    *,
    label: str = "RS 22:4",
    document_id: str = "506671",
    form_action: str = "./Law.aspx?d=506671",
    print_href: str = "LawPrint.aspx?d=506671",
    document: str = (
        "<p>&sect;4. &nbsp;Redesignated as R.S. 22:12 by Acts 2008, "
        "No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    return _range_redesignation_html(
        label=label,
        document_id=document_id,
        form_action=form_action,
        print_href=print_href,
        document=document,
        include_previous=include_previous,
        include_next=include_next,
    )


def _effective_date_redesignation_22_5_html(
    *,
    label: str = "RS 22:5",
    document_id: str = "506672",
    form_action: str = "./Law.aspx?d=506672",
    print_href: str = "LawPrint.aspx?d=506672",
    document: str = (
        "<p>&sect;5. &nbsp;Redesignated as R.S. 22:46 by Acts 2008, "
        "No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    return _range_redesignation_html(
        label=label,
        document_id=document_id,
        form_action=form_action,
        print_href=print_href,
        document=document,
        include_previous=include_previous,
        include_next=include_next,
    )


def _effective_date_redesignation_22_6_html(
    *,
    label: str = "RS 22:6",
    document_id: str = "506673",
    form_action: str = "./Law.aspx?d=506673",
    print_href: str = "LawPrint.aspx?d=506673",
    document: str = (
        "<p>&sect;6. &nbsp;Redesignated as R.S. 22:47 by Acts 2008, "
        "No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
    ),
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    return _range_redesignation_html(
        label=label,
        document_id=document_id,
        form_action=form_action,
        print_href=print_href,
        document=document,
        include_previous=include_previous,
        include_next=include_next,
    )


_TITLE_22_RENUMBERING_CASES = [
    pytest.param(
        "https://legis.la.gov/legis/Law.aspx?d=506674",
        "RS 22:7",
        "506674",
        "Redesignated from R.S. 22:13 by Acts 2008, No. 415, §1, "
        "eff. Jan. 1, 2009.",
        "redesignated_from_effective_date",
        id="rs-22-7-redesignated-from",
    ),
    pytest.param(
        "https://legis.la.gov/legis/Law.aspx?d=506668",
        "RS 22:8",
        "506668",
        "R.S. 22:8(A) redesignated as R.S. 22:3 and R.S. 22:8(B) and "
        "(C) redesignated as R.S. 22:2(J) and (K) by Acts 2008, No. 415, "
        "§1, eff. Jan. 1, 2009.",
        "split_redesignation_effective_date",
        id="rs-22-8-split-redesignation",
    ),
    pytest.param(
        "https://legis.la.gov/legis/Law.aspx?d=506675",
        "RS 22:9",
        "506675",
        "Redesignated as R.S. 22:2161 by Acts 2008, No. 415, §1, "
        "eff. Jan. 1, 2009.",
        "redesignated_effective_date",
        id="rs-22-9-redesignated-as",
    ),
    pytest.param(
        "https://legis.la.gov/legis/Law.aspx?d=506676",
        "RS 22:10",
        "506676",
        "Redesignated as R.S. 22:971 by Acts 2008, No. 415, §1, "
        "eff. Jan. 1, 2009.",
        "redesignated_effective_date",
        id="rs-22-10-redesignated-as",
    ),
    pytest.param(
        "https://legis.la.gov/legis/Law.aspx?d=506687",
        "RS 22:25.1",
        "506687",
        "Redesignated as R.S. 22:2231 by Acts 2008, No. 415, §1, "
        "eff. Jan. 1, 2009.",
        "redesignated_effective_date",
        id="rs-22-25-1-redesignated-as",
    ),
    pytest.param(
        "https://legis.la.gov/legis/Law.aspx?d=506689",
        "RS 22:25.2",
        "506689",
        "Redesignated as R.S. 22:2232 by Acts 2008, No. 415, §1, "
        "eff. Jan. 1, 2009.",
        "redesignated_effective_date",
        id="rs-22-25-2-redesignated-as",
    ),
    pytest.param(
        "https://legis.la.gov/legis/Law.aspx?d=506697",
        "RS 22:38",
        "506697",
        "Redesignated as R.S. 22:67 by Acts 2008, No. 415, §1, "
        "eff. Jan. 1, 2009.",
        "redesignated_effective_date",
        id="rs-22-38-redesignated-as",
    ),
    pytest.param(
        "https://legis.la.gov/legis/Law.aspx?d=506698",
        "RS 22:39",
        "506698",
        "Redesignated as R.S. 22:68 by Acts 2008, No. 415, §1, "
        "eff. Jan. 1, 2009.",
        "redesignated_effective_date",
        id="rs-22-39-redesignated-as",
    ),
    pytest.param(
        "https://legis.la.gov/legis/Law.aspx?d=506699",
        "RS 22:40",
        "506699",
        "Redesignated as R.S. 22:69 by Acts 2008, No. 415, §1, "
        "eff. Jan. 1, 2009.",
        "redesignated_effective_date",
        id="rs-22-40-redesignated-as",
    ),
]


def _title_22_renumbering_html(
    *,
    label: str,
    document_id: str,
    heading: str,
    form_action: str | None = None,
    print_href: str | None = None,
    document: str | None = None,
    include_previous: bool = True,
    include_next: bool = True,
) -> str:
    section = label.split(":", 1)[1]
    return _range_redesignation_html(
        label=label,
        document_id=document_id,
        form_action=form_action or f"./Law.aspx?d={document_id}",
        print_href=print_href or f"LawPrint.aspx?d={document_id}",
        document=document
        or f"<p>&sect;{section}. &nbsp;{heading}</p>",
        include_previous=include_previous,
        include_next=include_next,
    )


@pytest.mark.anyio
async def test_strict_frontier_recovers_nested_span_text_and_types_zero_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        "https://legis.la.gov/legis/Law.aspx?d=101",
        "https://legis.la.gov/legis/Law.aspx?d=102",
        "https://legis.la.gov/legis/Law.aspx?d=103",
        "https://legis.la.gov/legis/Law.aspx?d=104",
    ]
    active = b"""
    <span id="ctl00_PageBody_LabelName">RS 1:1</span>
    <span id="ctl00_PageBody_LabelDocument"><div id="WPMainDoc">
      <p><span><span>&sect;1. Short operative section</span></span></p>
      <p><span><span>This short Louisiana law remains operative and must not be
      discarded merely because its complete text is under 280 characters.</span></span></p>
    </div></span>
    """
    repealed = b"""
    <span id="ctl00_PageBody_LabelName">RS 1:2</span>
    <span id="ctl00_PageBody_LabelDocument"><p><span>
      &sect;2. Repealed by Acts 2008, No. 326, &sect;1.
    </span></p></span>
    """
    title_heading = b"""
    <span id="ctl00_PageBody_LabelName">RS 1</span>
    <span id="ctl00_PageBody_LabelDocument"><p><span>
      TITLE 1. GENERAL PROVISIONS
    </span></p></span>
    """
    blank_range = b"""
    <span id="ctl00_PageBody_LabelName">RS 9:352</span>
    <span id="ctl00_PageBody_LabelDocument"><p><span>
      &sect;352. &sect;&sect;352 to 356 [Blank].
    </span></p></span>
    """
    payload_by_url = dict(zip(urls, (active, repealed, title_heading, blank_range)))

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), payload_by_url)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=urls,
        max_statutes=None,
    )

    assert len(rows) == 1
    assert rows[0].section_number == "1"
    assert "under 280 characters" in rows[0].full_text
    assert rows[0].structured_data["content_sha256"] == hashlib.sha256(
        active
    ).hexdigest()
    assert rows[0].structured_data["official_frontier_closed"] is True

    frontier = scraper._last_louisiana_full_frontier
    assert frontier["closed"] is True
    assert frontier["law_pages_discovered"] == 4
    assert frontier["law_pages_requested"] == 4
    assert frontier["law_pages_fetched"] == 4
    assert frontier["law_pages_classified"] == 4
    assert frontier["statutes_emitted"] == 1
    assert frontier["terminal_pages_excluded"] == 3
    assert frontier["terminal_disposition_counts"] == {
        "blank": 1,
        "repealed": 1,
        "title_heading": 1,
    }
    assert {
        item["source_url"]: item["disposition"]
        for item in frontier["terminal_dispositions"]
    } == {urls[1]: "repealed", urls[2]: "title_heading", urls[3]: "blank"}


@pytest.mark.anyio
async def test_strict_frontier_fails_closed_on_untyped_parser_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=201"
    unknown = b"""
    <span id="ctl00_PageBody_LabelName">RS 1:3</span>
    <span id="ctl00_PageBody_LabelDocument"><p>&sect;3. Reserved</p></span>
    """

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: unknown})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    with pytest.raises(RuntimeError, match="left an official locator untyped"):
        await scraper._scrape_law_page_urls(
            code_name="Louisiana Revised Statutes",
            law_urls=[url],
            max_statutes=None,
        )

    assert scraper._last_louisiana_full_frontier["closed"] is False
    assert scraper._last_louisiana_full_frontier["unresolved_law_pages"] == [
        {
            "source_url": url,
            "content_sha256": hashlib.sha256(unknown).hexdigest(),
            "label": "RS 1:3",
            "error": "untyped parser miss",
        }
    ]


@pytest.mark.anyio
async def test_strict_frontier_rejects_originless_aligned_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=301"
    payload = b"""
    <span id="ctl00_PageBody_LabelName">RS 1:4</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;4. Provenance is required</p>
      <p>This otherwise valid section has no exact transport receipt.</p>
    </span>
    """

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload}, receipts=False)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    with pytest.raises(RuntimeError, match="lacked exact byte provenance"):
        await scraper._scrape_law_page_urls(
            code_name="Louisiana Revised Statutes",
            law_urls=[url],
            max_statutes=None,
        )

    assert scraper._last_louisiana_full_frontier["closed"] is False
    assert scraper._last_louisiana_full_frontier["law_pages_fetched"] == 0


def test_source_bound_classifier_types_exact_empty_official_locator() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=763423"
    digest = louisiana_law._EXACT_EMPTY_OFFICIAL_LOCATORS[url]["content_sha256"]
    html = _empty_official_locator_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        == "empty_official_locator"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=763423",
            "2e9db3dcbb9afe49bfa5679ea4355e4a2a68a4d82437068b25f0455651b0ca50",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=763423",
            "2e9db3dcbb9afe49bfa5679ea4355e4a2a68a4d82437068b25f0455651b0ca50",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=763423&copy=1",
            "2e9db3dcbb9afe49bfa5679ea4355e4a2a68a4d82437068b25f0455651b0ca50",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=763423",
            "0" * 64,
        ),
    ],
)
def test_source_bound_empty_locator_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _empty_official_locator_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _empty_official_locator_html(label="RS 13:2589.2"),
        _empty_official_locator_html(document_id="763424"),
        _empty_official_locator_html(form_action="./Law.aspx?d=763424"),
        _empty_official_locator_html(print_href="LawPrint.aspx?d=763424"),
        _empty_official_locator_html(
            document="<p>&sect;2589.1. This provision is now substantive.</p>"
        ),
        _empty_official_locator_html(document="<!-- upstream editorial marker -->"),
    ],
)
def test_source_bound_empty_locator_rejects_structure_or_substance_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=763423"
    digest = louisiana_law._EXACT_EMPTY_OFFICIAL_LOCATORS[url]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_malformed_blank_locator() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=781433"
    evidence = louisiana_law._EXACT_MALFORMED_BLANK_OFFICIAL_LOCATORS[url]
    html = _malformed_blank_official_locator_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "blank_editorial_typo"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=781433",
            "79f07b2ca2ad90affc7e75c7bd3fcf1d1398def1c4ee181861dc00761ec20b6b",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=781433",
            "79f07b2ca2ad90affc7e75c7bd3fcf1d1398def1c4ee181861dc00761ec20b6b",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=781433&copy=1",
            "79f07b2ca2ad90affc7e75c7bd3fcf1d1398def1c4ee181861dc00761ec20b6b",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=781433", "0" * 64),
    ],
)
def test_source_bound_malformed_blank_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _malformed_blank_official_locator_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _malformed_blank_official_locator_html(label="RS 13:5557"),
        _malformed_blank_official_locator_html(document_id="781434"),
        _malformed_blank_official_locator_html(form_action="./Law.aspx?d=781434"),
        _malformed_blank_official_locator_html(print_href="LawPrint.aspx?d=781434"),
        _malformed_blank_official_locator_html(document="<p>&sect;5556. [Blank]</p>"),
        _malformed_blank_official_locator_html(
            document=(
                "<p>&sect;5556. [Blank)]</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _malformed_blank_official_locator_html(include_previous=False),
        _malformed_blank_official_locator_html(include_next=False),
    ],
)
def test_source_bound_malformed_blank_rejects_structure_or_substance_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=781433"
    digest = louisiana_law._EXACT_MALFORMED_BLANK_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_blank_range_cross_reference() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=88919"
    evidence = louisiana_law._EXACT_BLANK_RANGE_CROSS_REFERENCE_OFFICIAL_LOCATORS[
        url
    ]
    html = _blank_range_cross_reference_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "blank_range_cross_reference"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=88919",
            "cc9e76f9cbe66aacbb702b7e5d6650bde9a83873efa6d692c34919396e680f87",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=88919",
            "cc9e76f9cbe66aacbb702b7e5d6650bde9a83873efa6d692c34919396e680f87",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=88919&copy=1",
            "cc9e76f9cbe66aacbb702b7e5d6650bde9a83873efa6d692c34919396e680f87",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=88919", "0" * 64),
    ],
)
def test_source_bound_blank_range_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _blank_range_cross_reference_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _blank_range_cross_reference_html(label="RS 33:130.432"),
        _blank_range_cross_reference_html(document_id="88920"),
        _blank_range_cross_reference_html(form_action="./Law.aspx?d=88920"),
        _blank_range_cross_reference_html(print_href="LawPrint.aspx?d=88920"),
        _blank_range_cross_reference_html(
            document=(
                '<p align="center" class="A0001">SUBPART B-19. FOURTEENTH '
                "AND SIXTEENTH WARDS</p>"
                '<p align="center" class="A0001">NEIGHBORHOOD DEVELOPMENT '
                "DISTRICT</p>"
                '<p align="justify" class="A0002">&sect;130.431. '
                "&sect;&sect;130.431-130.437 Blank. See R.S. 33:9083.</p>"
            )
        ),
        _blank_range_cross_reference_html(
            document=(
                '<p align="center" class="A0001">SUBPART B-19. FOURTEENTH '
                "AND SIXTEENTH WARDS</p>"
                '<p align="center" class="A0001">NEIGHBORHOOD DEVELOPMENT '
                "DISTRICT</p>"
                '<p align="justify" class="A0002">&sect;130.431. '
                "&sect;&sect;130.431-130.436 Blank. See R.S. 33:9084.</p>"
            )
        ),
        _blank_range_cross_reference_html().replace(
            'class="A0002"', 'class="A0003"'
        ),
        _blank_range_cross_reference_html().replace(
            '<form id="aspnetForm" name="aspnetForm" method="post"',
            '<form id="aspnetForm" name="aspnetForm" method="get"',
        ),
        _blank_range_cross_reference_html().replace(
            "</span>\n    </form>",
            "<p>This operative paragraph prevents exclusion.</p></span>\n    </form>",
        ),
    ],
)
def test_source_bound_blank_range_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=88919"
    digest = louisiana_law._EXACT_BLANK_RANGE_CROSS_REFERENCE_OFFICIAL_LOCATORS[
        url
    ]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_malformed_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=781433"
    payload = _malformed_blank_official_locator_html().encode()
    evidence = louisiana_law._EXACT_MALFORMED_BLANK_OFFICIAL_LOCATORS[url]
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "blank_editorial_typo": 1
    }


@pytest.mark.parametrize(
    ("url", "html"),
    [
        (
            "https://legis.la.gov/legis/Law.aspx?d=78416",
            _act_section_suffix_redesignation_html(),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=814013",
            _act_section_suffix_redesignation_html(
                label="RS 14:32.9.1",
                document_id="814013",
                form_action="./Law.aspx?d=814013",
                print_href="LawPrint.aspx?d=814013",
                document=(
                    "<p>&sect;32.9.1. Redesignated as R.S. 14:87.11 by "
                    "Acts 2022, No. 545, &sect;6A.</p>"
                ),
            ),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=451831",
            _act_section_suffix_redesignation_html(
                label="RS 14:32.11",
                document_id="451831",
                form_action="./Law.aspx?d=451831",
                print_href="LawPrint.aspx?d=451831",
                document=(
                    "<p>&sect;32.11. Redesignated as R.S. 14:87.12 by "
                    "Acts 2022, No. 545, &sect;6A.</p>"
                ),
            ),
        ),
    ],
)
def test_source_bound_classifier_types_exact_act_section_suffix_redesignation(
    url: str,
    html: str,
) -> None:
    evidence = louisiana_law._EXACT_ACT_SECTION_SUFFIX_REDESIGNATIONS[url]

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_act_section_suffix"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=78416",
            "f2dd8993f7e28aaabc6d13755280451f71eade08e6744b63fc32036b1f3f7116",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=78416",
            "f2dd8993f7e28aaabc6d13755280451f71eade08e6744b63fc32036b1f3f7116",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=78416&copy=1",
            "f2dd8993f7e28aaabc6d13755280451f71eade08e6744b63fc32036b1f3f7116",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=78416", "0" * 64),
        (
            "https://legis.la.gov/legis/Law.aspx?d=814013&copy=1",
            "7b66e6db23cf965291206a00ccdb14e8f2493bda19adab60db7d17972c9ce1f8",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=814013", "0" * 64),
        (
            "https://legis.la.gov/legis/Law.aspx?d=451831&copy=1",
            "cf82c753e0ba0fa288fc1895b15efa2a15248e62e01f095a27e862c1c32208c1",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=451831", "0" * 64),
    ],
)
def test_source_bound_act_section_suffix_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _act_section_suffix_redesignation_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _act_section_suffix_redesignation_html(label="RS 14:32.8"),
        _act_section_suffix_redesignation_html(document_id="78417"),
        _act_section_suffix_redesignation_html(form_action="./Law.aspx?d=78417"),
        _act_section_suffix_redesignation_html(print_href="LawPrint.aspx?d=78417"),
        _act_section_suffix_redesignation_html(
            document=(
                "<p>&sect;32.9. Redesignated as R.S. 14:32.9 by Acts 2022, "
                "No. 545, &sect;6A.</p>"
            )
        ),
        _act_section_suffix_redesignation_html(
            document=(
                "<p>&sect;32.9. Redesignated as R.S. 14:87.10 by Acts 2022, "
                "No. 545, &sect;6A.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _act_section_suffix_redesignation_html(include_previous=False),
        _act_section_suffix_redesignation_html(include_next=False),
    ],
)
def test_source_bound_act_section_suffix_rejects_structure_or_substance_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=78416"
    digest = louisiana_law._EXACT_ACT_SECTION_SUFFIX_REDESIGNATIONS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _act_section_suffix_redesignation_html(
            label="RS 14:32.9.2",
            document_id="814013",
            form_action="./Law.aspx?d=814013",
            print_href="LawPrint.aspx?d=814013",
            document=(
                "<p>&sect;32.9.1. Redesignated as R.S. 14:87.11 by Acts "
                "2022, No. 545, &sect;6A.</p>"
            ),
        ),
        _act_section_suffix_redesignation_html(
            label="RS 14:32.9.1",
            document_id="814013",
            form_action="./Law.aspx?d=814013",
            print_href="LawPrint.aspx?d=814013",
            document=(
                "<p>&sect;32.9.1. Redesignated as R.S. 14:32.9.1 by Acts "
                "2022, No. 545, &sect;6A.</p>"
            ),
        ),
        _act_section_suffix_redesignation_html(
            label="RS 14:32.9.1",
            document_id="814013",
            form_action="./Law.aspx?d=814013",
            print_href="LawPrint.aspx?d=814013",
            document=(
                "<p>&sect;32.9.1. Redesignated as R.S. 14:87.11 by Acts "
                "2022, No. 545, &sect;6A.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            ),
        ),
    ],
)
def test_second_source_bound_act_section_suffix_rejects_drift(html: str) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=814013"
    digest = louisiana_law._EXACT_ACT_SECTION_SUFFIX_REDESIGNATIONS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _act_section_suffix_redesignation_html(
            label="RS 14:32.12",
            document_id="451831",
            form_action="./Law.aspx?d=451831",
            print_href="LawPrint.aspx?d=451831",
            document=(
                "<p>&sect;32.11. Redesignated as R.S. 14:87.12 by Acts "
                "2022, No. 545, &sect;6A.</p>"
            ),
        ),
        _act_section_suffix_redesignation_html(
            label="RS 14:32.11",
            document_id="451832",
            form_action="./Law.aspx?d=451831",
            print_href="LawPrint.aspx?d=451831",
            document=(
                "<p>&sect;32.11. Redesignated as R.S. 14:87.12 by Acts "
                "2022, No. 545, &sect;6A.</p>"
            ),
        ),
        _act_section_suffix_redesignation_html(
            label="RS 14:32.11",
            document_id="451831",
            form_action="./Law.aspx?d=451832",
            print_href="LawPrint.aspx?d=451831",
            document=(
                "<p>&sect;32.11. Redesignated as R.S. 14:87.12 by Acts "
                "2022, No. 545, &sect;6A.</p>"
            ),
        ),
        _act_section_suffix_redesignation_html(
            label="RS 14:32.11",
            document_id="451831",
            form_action="./Law.aspx?d=451831",
            print_href="LawPrint.aspx?d=451832",
            document=(
                "<p>&sect;32.11. Redesignated as R.S. 14:87.12 by Acts "
                "2022, No. 545, &sect;6A.</p>"
            ),
        ),
        _act_section_suffix_redesignation_html(
            label="RS 14:32.11",
            document_id="451831",
            form_action="./Law.aspx?d=451831",
            print_href="LawPrint.aspx?d=451831",
            document=(
                "<p>&sect;32.11. Redesignated as R.S. 14:32.11 by Acts "
                "2022, No. 545, &sect;6A.</p>"
            ),
        ),
        _act_section_suffix_redesignation_html(
            label="RS 14:32.11",
            document_id="451831",
            form_action="./Law.aspx?d=451831",
            print_href="LawPrint.aspx?d=451831",
            document=(
                "<p>&sect;32.11. Redesignated as R.S. 14:87.12 by Acts "
                "2022, No. 545, &sect;6A.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            ),
        ),
        _act_section_suffix_redesignation_html(
            label="RS 14:32.11",
            document_id="451831",
            form_action="./Law.aspx?d=451831",
            print_href="LawPrint.aspx?d=451831",
            document=(
                "<p>&sect;32.11. Redesignated as R.S. 14:87.12 by Acts "
                "2022, No. 545, &sect;6A.</p>"
            ),
            include_previous=False,
        ),
        _act_section_suffix_redesignation_html(
            label="RS 14:32.11",
            document_id="451831",
            form_action="./Law.aspx?d=451831",
            print_href="LawPrint.aspx?d=451831",
            document=(
                "<p>&sect;32.11. Redesignated as R.S. 14:87.12 by Acts "
                "2022, No. 545, &sect;6A.</p>"
            ),
            include_next=False,
        ),
    ],
)
def test_third_source_bound_act_section_suffix_rejects_drift(html: str) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=451831"
    digest = louisiana_law._EXACT_ACT_SECTION_SUFFIX_REDESIGNATIONS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_article_reserved() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85324"
    evidence = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url]
    html = _article_reserved_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "reserved_article"
    )


def test_source_bound_classifier_types_exact_article_12_reserved() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85333"
    evidence = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url]
    html = _article_12_reserved_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "reserved_article"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=85333",
            "fb2fcdced228aa79f43e313316a4079051aa29b13cc2b5e6fea5f93788494a26",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=85333",
            "fb2fcdced228aa79f43e313316a4079051aa29b13cc2b5e6fea5f93788494a26",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85333&copy=1",
            "fb2fcdced228aa79f43e313316a4079051aa29b13cc2b5e6fea5f93788494a26",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=85333", "0" * 64),
    ],
)
def test_source_bound_article_12_reserved_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _article_12_reserved_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _article_12_reserved_html(label="RS 29:113"),
        _article_12_reserved_html(label_class="law-title"),
        _article_12_reserved_html(label_style="font-size:large;"),
        _article_12_reserved_html(document_id="85334"),
    ],
)
def test_source_bound_article_12_reserved_rejects_identity_drift(html: str) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85333"
    digest = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _article_12_reserved_html(form_action="./Law.aspx?d=85334"),
        _article_12_reserved_html(form_method="get"),
        _article_12_reserved_html(form_name="lawForm"),
        _article_12_reserved_html(print_href="LawPrint.aspx?d=85334"),
        _article_12_reserved_html(print_target="_self"),
        _article_12_reserved_html(print_title="Print"),
    ],
)
def test_source_bound_article_12_reserved_rejects_form_or_print_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85333"
    digest = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _article_12_reserved_html(include_previous=False),
        _article_12_reserved_html(include_next=False),
        _article_12_reserved_html(previous_name="previous"),
        _article_12_reserved_html(previous_title="previous"),
        _article_12_reserved_html(previous_type="button"),
        _article_12_reserved_html(previous_value="<"),
        _article_12_reserved_html(next_name="next"),
        _article_12_reserved_html(next_title="next"),
        _article_12_reserved_html(next_type="button"),
        _article_12_reserved_html(next_value=">"),
    ],
)
def test_source_bound_article_12_reserved_rejects_navigation_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85333"
    digest = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _article_12_reserved_html(
            document='<div align="justify" class="A0001">'
            "&sect;112. Article 12. [Reserved]</div>"
        ),
        _article_12_reserved_html(
            document='<p align="left" class="A0001">'
            "&sect;112. Article 12. [Reserved]</p>"
        ),
        _article_12_reserved_html(
            document='<p align="justify" class="A0002">'
            "&sect;112. Article 12. [Reserved]</p>"
        ),
        _article_12_reserved_html(
            document=(
                '<p align="justify" class="A0001">'
                "&sect;112. Article 12. [Reserved]</p>"
                "<p>Operative text prevents terminal exclusion.</p>"
            )
        ),
        _article_12_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;112. Article 13. [Reserved]</p>"
        ),
        _article_12_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;112. Article 12. [Repealed]</p>"
        ),
        _article_12_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;112. Article 12. [Reserved].</p>"
        ),
    ],
)
def test_source_bound_article_12_reserved_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85333"
    digest = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_article_68_reserved() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85397"
    evidence = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url]
    html = _article_68_reserved_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "reserved_article"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=85397",
            "b0051d7f20b1f81442984ca1c7ccf559af4bdfdbdf7d3b42bff47a8e475d0f6b",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=85397",
            "b0051d7f20b1f81442984ca1c7ccf559af4bdfdbdf7d3b42bff47a8e475d0f6b",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85397&copy=1",
            "b0051d7f20b1f81442984ca1c7ccf559af4bdfdbdf7d3b42bff47a8e475d0f6b",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=85397", "0" * 64),
    ],
)
def test_source_bound_article_68_reserved_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _article_68_reserved_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _article_68_reserved_html(label="RS 29:169"),
        _article_68_reserved_html(label_class="law-title"),
        _article_68_reserved_html(label_style="font-size:large;"),
        _article_68_reserved_html(document_id="85398"),
        _article_68_reserved_html(form_action="./Law.aspx?d=85398"),
        _article_68_reserved_html(form_method="get"),
        _article_68_reserved_html(form_name="lawForm"),
        _article_68_reserved_html(print_href="LawPrint.aspx?d=85398"),
        _article_68_reserved_html(print_target="_self"),
        _article_68_reserved_html(print_title="Print"),
        _article_68_reserved_html(include_previous=False),
        _article_68_reserved_html(include_next=False),
        _article_68_reserved_html(previous_name="previous"),
        _article_68_reserved_html(previous_title="previous"),
        _article_68_reserved_html(previous_type="button"),
        _article_68_reserved_html(previous_value="<"),
        _article_68_reserved_html(next_name="next"),
        _article_68_reserved_html(next_title="next"),
        _article_68_reserved_html(next_type="button"),
        _article_68_reserved_html(next_value=">"),
        _article_68_reserved_html(
            document='<div align="justify" class="A0001">'
            "&sect;168. Article 68. [Reserved]</div>"
        ),
        _article_68_reserved_html(
            document='<p align="left" class="A0001">'
            "&sect;168. Article 68. [Reserved]</p>"
        ),
        _article_68_reserved_html(
            document='<p align="justify" class="A0002">'
            "&sect;168. Article 68. [Reserved]</p>"
        ),
        _article_68_reserved_html(
            document=(
                '<p align="justify" class="A0001">'
                "&sect;168. Article 68. [Reserved]</p>"
                "<p>Operative text prevents terminal exclusion.</p>"
            )
        ),
        _article_68_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;168. Article 69. [Reserved]</p>"
        ),
        _article_68_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;168. Article 68. [Repealed]</p>"
        ),
        _article_68_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;168. Article 68. [Reserved].</p>"
        ),
    ],
)
def test_source_bound_article_68_reserved_rejects_exact_identity_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85397"
    digest = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_article_69_reserved() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85398"
    evidence = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url]
    html = _article_69_reserved_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "reserved_article"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=85398",
            "414b022825f804be4ac080704a2bf87085cf711aab45cc45d1d9ad54933bc0cb",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=85398",
            "414b022825f804be4ac080704a2bf87085cf711aab45cc45d1d9ad54933bc0cb",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85398&copy=1",
            "414b022825f804be4ac080704a2bf87085cf711aab45cc45d1d9ad54933bc0cb",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=85398", "0" * 64),
    ],
)
def test_source_bound_article_69_reserved_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _article_69_reserved_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _article_69_reserved_html(label="RS 29:170"),
        _article_69_reserved_html(label_class="law-title"),
        _article_69_reserved_html(label_style="font-size:large;"),
        _article_69_reserved_html(document_id="85399"),
        _article_69_reserved_html(form_action="./Law.aspx?d=85399"),
        _article_69_reserved_html(form_method="get"),
        _article_69_reserved_html(form_name="lawForm"),
        _article_69_reserved_html(print_href="LawPrint.aspx?d=85399"),
        _article_69_reserved_html(print_target="_self"),
        _article_69_reserved_html(print_title="Print"),
        _article_69_reserved_html(include_previous=False),
        _article_69_reserved_html(include_next=False),
        _article_69_reserved_html(previous_name="previous"),
        _article_69_reserved_html(previous_title="previous"),
        _article_69_reserved_html(previous_type="button"),
        _article_69_reserved_html(previous_value="<"),
        _article_69_reserved_html(next_name="next"),
        _article_69_reserved_html(next_title="next"),
        _article_69_reserved_html(next_type="button"),
        _article_69_reserved_html(next_value=">"),
        _article_69_reserved_html(
            document='<div align="justify" class="A0001">'
            "&sect;169. Article 69. [Reserved]</div>"
        ),
        _article_69_reserved_html(
            document='<p align="left" class="A0001">'
            "&sect;169. Article 69. [Reserved]</p>"
        ),
        _article_69_reserved_html(
            document='<p align="justify" class="A0002">'
            "&sect;169. Article 69. [Reserved]</p>"
        ),
        _article_69_reserved_html(
            document=(
                '<p align="justify" class="A0001">'
                "&sect;169. Article 69. [Reserved]</p>"
                "<p>Operative text prevents terminal exclusion.</p>"
            )
        ),
        _article_69_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;169. Article 70. [Reserved]</p>"
        ),
        _article_69_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;169. Article 69. [Repealed]</p>"
        ),
        _article_69_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;169. Article 69. [Reserved].</p>"
        ),
    ],
)
def test_source_bound_article_69_reserved_rejects_exact_identity_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85398"
    digest = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_article_106_reserved() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85440"
    evidence = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url]

    assert terminal_disposition_from_law_html(_article_106_reserved_html()) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            _article_106_reserved_html(),
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "reserved_article"
    )


@pytest.mark.parametrize(
    ("document_id", "label", "section", "article"),
    _ADDITIONAL_ARTICLE_RESERVED_CASES,
)
def test_source_bound_classifier_types_batched_article_reserved_contracts(
    document_id: str,
    label: str,
    section: str,
    article: str,
) -> None:
    url = f"https://legis.la.gov/legis/Law.aspx?d={document_id}"
    evidence = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url]
    html = _article_reserved_html(
        label=label,
        document_id=document_id,
        form_action=f"./Law.aspx?d={document_id}",
        print_href=f"LawPrint.aspx?d={document_id}",
        document=(
            '<p align="justify" class="A0001">'
            f"&sect;{section}. &nbsp;Article {article}. &nbsp;[Reserved] "
            "</p>"
        ),
    )

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "reserved_article"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256", "html"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=85440",
            "48669337b481bc9f1fb9ca5d5847601789bd1bb35ea4c8df30cc980a9db09fac",
            _article_106_reserved_html(),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85440",
            "0" * 64,
            _article_106_reserved_html(),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85440",
            "48669337b481bc9f1fb9ca5d5847601789bd1bb35ea4c8df30cc980a9db09fac",
            _article_106_reserved_html(label="RS 29:207"),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85440",
            "48669337b481bc9f1fb9ca5d5847601789bd1bb35ea4c8df30cc980a9db09fac",
            _article_106_reserved_html(document_id="85441"),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85440",
            "48669337b481bc9f1fb9ca5d5847601789bd1bb35ea4c8df30cc980a9db09fac",
            _article_106_reserved_html(
                document='<p align="justify" class="A0001">'
                "&sect;206. Article 106. [Reserved]</p>"
                "<p>Operative text prevents terminal exclusion.</p>"
            ),
        ),
    ],
)
def test_source_bound_article_106_reserved_rejects_contract_drift(
    source_url: str,
    content_sha256: str,
    html: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=85324",
            "0a94724d1aca9616319d05881afd3b8de0571ba4a432520da8087e002ac5b361",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=85324",
            "0a94724d1aca9616319d05881afd3b8de0571ba4a432520da8087e002ac5b361",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85324&copy=1",
            "0a94724d1aca9616319d05881afd3b8de0571ba4a432520da8087e002ac5b361",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=85324", "0" * 64),
    ],
)
def test_source_bound_article_reserved_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _article_reserved_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _article_reserved_html(label="RS 29:105"),
        _article_reserved_html(label_class="law-title"),
        _article_reserved_html(label_style="font-size:large;"),
        _article_reserved_html(document_id="85325"),
    ],
)
def test_source_bound_article_reserved_rejects_label_or_document_identity_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85324"
    digest = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _article_reserved_html(form_action="./Law.aspx?d=85325"),
        _article_reserved_html(form_method="get"),
        _article_reserved_html(form_name="lawForm"),
        _article_reserved_html(print_href="LawPrint.aspx?d=85325"),
        _article_reserved_html(print_target="_self"),
        _article_reserved_html(print_title="Print"),
    ],
)
def test_source_bound_article_reserved_rejects_form_or_print_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85324"
    digest = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _article_reserved_html(include_previous=False),
        _article_reserved_html(include_next=False),
        _article_reserved_html(previous_name="previous"),
        _article_reserved_html(previous_title="previous"),
        _article_reserved_html(previous_type="button"),
        _article_reserved_html(previous_value="<"),
        _article_reserved_html(next_name="next"),
        _article_reserved_html(next_title="next"),
        _article_reserved_html(next_type="button"),
        _article_reserved_html(next_value=">"),
    ],
)
def test_source_bound_article_reserved_rejects_navigation_drift(html: str) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85324"
    digest = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _article_reserved_html(
            document='<div align="justify" class="A0001">'
            "&sect;104. Article 4. [Reserved]</div>"
        ),
        _article_reserved_html(
            document='<p align="left" class="A0001">'
            "&sect;104. Article 4. [Reserved]</p>"
        ),
        _article_reserved_html(
            document='<p align="justify" class="A0002">'
            "&sect;104. Article 4. [Reserved]</p>"
        ),
        _article_reserved_html(
            document=(
                '<p align="justify" class="A0001">'
                "&sect;104. Article 4. [Reserved]</p>"
                "<p>Operative text prevents terminal exclusion.</p>"
            )
        ),
        _article_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;104. Article 5. [Reserved]</p>"
        ),
        _article_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;104. Article 4. [Repealed]</p>"
        ),
        _article_reserved_html(
            document='<p align="justify" class="A0001">'
            "&sect;104. Article 4. [Reserved].</p>"
        ),
    ],
)
def test_source_bound_article_reserved_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85324"
    digest = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    "url",
    sorted(louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS),
)
def test_source_bound_article_reserved_replays_retained_contract(url: str) -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_LA_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Louisiana acquisition evidence")

    evidence = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url]
    jurisdiction_root = Path(evidence_root) / "LA"
    payload = (
        jurisdiction_root / "objects" / f'{evidence["content_sha256"]}.bin'
    ).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == evidence["content_sha256"]
    html = payload.decode("utf-8", errors="replace")
    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "reserved_article"
    )

    receipt = json.loads(
        (
            jurisdiction_root / "fetches" / f'{evidence["receipt_sha256"]}.json'
        ).read_bytes()
    )["parser_input_envelope"]["acquisition"]["receipt"]
    assert receipt["receipt_sha256"] == evidence["receipt_sha256"]
    assert receipt["receipt_cid"] == evidence["receipt_cid"]
    assert receipt["endpoint"] == url
    assert receipt["response_status"] == 200
    assert receipt["content"] == {
        "byte_size": len(payload),
        "cid": evidence["content_cid"],
        "sha256": evidence["content_sha256"],
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    sorted(louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS),
)
async def test_strict_frontier_closes_retained_article_reserved(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_LA_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Louisiana acquisition evidence")

    evidence = louisiana_law._EXACT_ARTICLE_RESERVED_OFFICIAL_LOCATORS[url]
    payload = (
        Path(evidence_root)
        / "LA"
        / "objects"
        / f'{evidence["content_sha256"]}.bin'
    ).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == evidence["content_sha256"]

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    frontier = scraper._last_louisiana_full_frontier
    assert frontier["closed"] is True
    assert frontier["law_pages_discovered"] == 1
    assert frontier["law_pages_requested"] == 1
    assert frontier["law_pages_fetched"] == 1
    assert frontier["law_pages_classified"] == 1
    assert frontier["terminal_pages_excluded"] == 1
    assert frontier["terminal_disposition_counts"] == {"reserved_article": 1}


@pytest.mark.parametrize(
    ("url", "html"),
    [
        (
            "https://legis.la.gov/legis/Law.aspx?d=78995",
            _parenthesized_reserved_html(),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=451967",
            _parenthesized_reserved_html(
                label="RS 15:172",
                document_id="451967",
                form_action="./Law.aspx?d=451967",
                print_href="LawPrint.aspx?d=451967",
                document="<p>&sect;172. (Reserved).</p>",
            ),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=451972",
            _parenthesized_reserved_html(
                label="RS 15:177",
                document_id="451972",
                form_action="./Law.aspx?d=451972",
                print_href="LawPrint.aspx?d=451972",
                document="<p>&sect;177. (Reserved)</p>",
            ),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=452049",
            _parenthesized_reserved_html(
                label="RS 15:184",
                document_id="452049",
                form_action="./Law.aspx?d=452049",
                print_href="LawPrint.aspx?d=452049",
                document="<p>&sect;184. (Reserved)</p>",
            ),
        ),
    ],
)
def test_source_bound_classifier_types_exact_parenthesized_reserved(
    url: str,
    html: str,
) -> None:
    evidence = louisiana_law._EXACT_PARENTHESIZED_RESERVED_OFFICIAL_LOCATORS[
        url
    ]

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "reserved_parenthesized"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=78995",
            "2c64c27e8d8215238ef796742f26d0b9102445b9e687cf502e74886e436f36a0",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=78995",
            "2c64c27e8d8215238ef796742f26d0b9102445b9e687cf502e74886e436f36a0",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=78995&copy=1",
            "2c64c27e8d8215238ef796742f26d0b9102445b9e687cf502e74886e436f36a0",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=78995", "0" * 64),
    ],
)
def test_source_bound_parenthesized_reserved_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _parenthesized_reserved_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _parenthesized_reserved_html(label="RS 15:172"),
        _parenthesized_reserved_html(document_id="78996"),
        _parenthesized_reserved_html(form_action="./Law.aspx?d=78996"),
        _parenthesized_reserved_html(print_href="LawPrint.aspx?d=78996"),
        _parenthesized_reserved_html(document="<p>&sect;171. Reserved.</p>"),
        _parenthesized_reserved_html(document="<p>&sect;171. (Repealed).</p>"),
        _parenthesized_reserved_html(
            document=(
                "<p>&sect;171. (Reserved).</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _parenthesized_reserved_html(include_previous=False),
        _parenthesized_reserved_html(include_next=False),
    ],
)
def test_source_bound_parenthesized_reserved_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=78995"
    digest = louisiana_law._EXACT_PARENTHESIZED_RESERVED_OFFICIAL_LOCATORS[
        url
    ]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=451967",
            "8f90e3d08af22e6b4b2c66b592222ad4b5b81f7088d5f822a6b133a71763cdb5",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=451967",
            "8f90e3d08af22e6b4b2c66b592222ad4b5b81f7088d5f822a6b133a71763cdb5",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=451967&copy=1",
            "8f90e3d08af22e6b4b2c66b592222ad4b5b81f7088d5f822a6b133a71763cdb5",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=451967", "0" * 64),
    ],
)
def test_source_bound_second_parenthesized_reserved_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    html = _parenthesized_reserved_html(
        label="RS 15:172",
        document_id="451967",
        form_action="./Law.aspx?d=451967",
        print_href="LawPrint.aspx?d=451967",
        document="<p>&sect;172. (Reserved).</p>",
    )
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _parenthesized_reserved_html(
            label="RS 15:171",
            document_id="451967",
            form_action="./Law.aspx?d=451967",
            print_href="LawPrint.aspx?d=451967",
            document="<p>&sect;172. (Reserved).</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:172",
            document_id="451968",
            form_action="./Law.aspx?d=451967",
            print_href="LawPrint.aspx?d=451967",
            document="<p>&sect;172. (Reserved).</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:172",
            document_id="451967",
            form_action="./Law.aspx?d=451968",
            print_href="LawPrint.aspx?d=451967",
            document="<p>&sect;172. (Reserved).</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:172",
            document_id="451967",
            form_action="./Law.aspx?d=451967",
            print_href="LawPrint.aspx?d=451968",
            document="<p>&sect;172. (Reserved).</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:172",
            document_id="451967",
            form_action="./Law.aspx?d=451967",
            print_href="LawPrint.aspx?d=451967",
            document="<p>&sect;172. Reserved.</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:172",
            document_id="451967",
            form_action="./Law.aspx?d=451967",
            print_href="LawPrint.aspx?d=451967",
            document="<p>&sect;172. (Repealed).</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:172",
            document_id="451967",
            form_action="./Law.aspx?d=451967",
            print_href="LawPrint.aspx?d=451967",
            document=(
                "<p>&sect;172. (Reserved).</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            ),
        ),
        _parenthesized_reserved_html(
            label="RS 15:172",
            document_id="451967",
            form_action="./Law.aspx?d=451967",
            print_href="LawPrint.aspx?d=451967",
            document="<p>&sect;172. (Reserved).</p>",
            include_previous=False,
        ),
        _parenthesized_reserved_html(
            label="RS 15:172",
            document_id="451967",
            form_action="./Law.aspx?d=451967",
            print_href="LawPrint.aspx?d=451967",
            document="<p>&sect;172. (Reserved).</p>",
            include_next=False,
        ),
    ],
)
def test_source_bound_second_parenthesized_reserved_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=451967"
    digest = louisiana_law._EXACT_PARENTHESIZED_RESERVED_OFFICIAL_LOCATORS[
        url
    ]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=451972",
            "5db5797a53f7a0db4d3ca35ba2cddc3d2e94851ee30a30d4496fe836d5539d49",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=451972",
            "5db5797a53f7a0db4d3ca35ba2cddc3d2e94851ee30a30d4496fe836d5539d49",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=451972&copy=1",
            "5db5797a53f7a0db4d3ca35ba2cddc3d2e94851ee30a30d4496fe836d5539d49",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=451972", "0" * 64),
    ],
)
def test_source_bound_third_parenthesized_reserved_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    html = _parenthesized_reserved_html(
        label="RS 15:177",
        document_id="451972",
        form_action="./Law.aspx?d=451972",
        print_href="LawPrint.aspx?d=451972",
        document="<p>&sect;177. (Reserved)</p>",
    )
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _parenthesized_reserved_html(
            label="RS 15:178",
            document_id="451972",
            form_action="./Law.aspx?d=451972",
            print_href="LawPrint.aspx?d=451972",
            document="<p>&sect;177. (Reserved)</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:177",
            document_id="451973",
            form_action="./Law.aspx?d=451972",
            print_href="LawPrint.aspx?d=451972",
            document="<p>&sect;177. (Reserved)</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:177",
            document_id="451972",
            form_action="./Law.aspx?d=451973",
            print_href="LawPrint.aspx?d=451972",
            document="<p>&sect;177. (Reserved)</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:177",
            document_id="451972",
            form_action="./Law.aspx?d=451972",
            print_href="LawPrint.aspx?d=451973",
            document="<p>&sect;177. (Reserved)</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:177",
            document_id="451972",
            form_action="./Law.aspx?d=451972",
            print_href="LawPrint.aspx?d=451972",
            document="<p>&sect;177. (Reserved).</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:177",
            document_id="451972",
            form_action="./Law.aspx?d=451972",
            print_href="LawPrint.aspx?d=451972",
            document="<p>&sect;177. (Repealed)</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:177",
            document_id="451972",
            form_action="./Law.aspx?d=451972",
            print_href="LawPrint.aspx?d=451972",
            document=(
                "<p>&sect;177. (Reserved)</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            ),
        ),
        _parenthesized_reserved_html(
            label="RS 15:177",
            document_id="451972",
            form_action="./Law.aspx?d=451972",
            print_href="LawPrint.aspx?d=451972",
            document="<p>&sect;177. (Reserved)</p>",
            include_previous=False,
        ),
        _parenthesized_reserved_html(
            label="RS 15:177",
            document_id="451972",
            form_action="./Law.aspx?d=451972",
            print_href="LawPrint.aspx?d=451972",
            document="<p>&sect;177. (Reserved)</p>",
            include_next=False,
        ),
    ],
)
def test_source_bound_third_parenthesized_reserved_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=451972"
    digest = louisiana_law._EXACT_PARENTHESIZED_RESERVED_OFFICIAL_LOCATORS[
        url
    ]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=452049",
            "689c6da918708c70c91c9685549dc11c51ea2eb86d74c2c73e164446d1c3acdd",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=452049",
            "689c6da918708c70c91c9685549dc11c51ea2eb86d74c2c73e164446d1c3acdd",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=452049&copy=1",
            "689c6da918708c70c91c9685549dc11c51ea2eb86d74c2c73e164446d1c3acdd",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=452049", "0" * 64),
    ],
)
def test_source_bound_fourth_parenthesized_reserved_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    html = _parenthesized_reserved_html(
        label="RS 15:184",
        document_id="452049",
        form_action="./Law.aspx?d=452049",
        print_href="LawPrint.aspx?d=452049",
        document="<p>&sect;184. (Reserved)</p>",
    )
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _parenthesized_reserved_html(
            label="RS 15:185",
            document_id="452049",
            form_action="./Law.aspx?d=452049",
            print_href="LawPrint.aspx?d=452049",
            document="<p>&sect;184. (Reserved)</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:184",
            document_id="452050",
            form_action="./Law.aspx?d=452049",
            print_href="LawPrint.aspx?d=452049",
            document="<p>&sect;184. (Reserved)</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:184",
            document_id="452049",
            form_action="./Law.aspx?d=452050",
            print_href="LawPrint.aspx?d=452049",
            document="<p>&sect;184. (Reserved)</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:184",
            document_id="452049",
            form_action="./Law.aspx?d=452049",
            print_href="LawPrint.aspx?d=452050",
            document="<p>&sect;184. (Reserved)</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:184",
            document_id="452049",
            form_action="./Law.aspx?d=452049",
            print_href="LawPrint.aspx?d=452049",
            document="<p>&sect;184. (Reserved).</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:184",
            document_id="452049",
            form_action="./Law.aspx?d=452049",
            print_href="LawPrint.aspx?d=452049",
            document="<p>&sect;184. (Repealed)</p>",
        ),
        _parenthesized_reserved_html(
            label="RS 15:184",
            document_id="452049",
            form_action="./Law.aspx?d=452049",
            print_href="LawPrint.aspx?d=452049",
            document=(
                "<p>&sect;184. (Reserved)</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            ),
        ),
        _parenthesized_reserved_html(
            label="RS 15:184",
            document_id="452049",
            form_action="./Law.aspx?d=452049",
            print_href="LawPrint.aspx?d=452049",
            document="<p>&sect;184. (Reserved)</p>",
            include_previous=False,
        ),
        _parenthesized_reserved_html(
            label="RS 15:184",
            document_id="452049",
            form_action="./Law.aspx?d=452049",
            print_href="LawPrint.aspx?d=452049",
            document="<p>&sect;184. (Reserved)</p>",
            include_next=False,
        ),
    ],
)
def test_source_bound_fourth_parenthesized_reserved_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=452049"
    digest = louisiana_law._EXACT_PARENTHESIZED_RESERVED_OFFICIAL_LOCATORS[
        url
    ]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_omitted_as_obsolete() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=79701"
    evidence = louisiana_law._EXACT_OMITTED_AS_OBSOLETE_OFFICIAL_LOCATORS[url]
    html = _omitted_as_obsolete_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "omitted_as_obsolete"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=79701",
            "c19a918b4db58bcc026ffcd8faa949a6e635f7dc936cf39c388303be8089508a",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=79701",
            "c19a918b4db58bcc026ffcd8faa949a6e635f7dc936cf39c388303be8089508a",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=79701&copy=1",
            "c19a918b4db58bcc026ffcd8faa949a6e635f7dc936cf39c388303be8089508a",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=79701", "0" * 64),
    ],
)
def test_source_bound_omitted_as_obsolete_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _omitted_as_obsolete_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _omitted_as_obsolete_html(label="RS 16:84"),
        _omitted_as_obsolete_html(document_id="79702"),
        _omitted_as_obsolete_html(form_action="./Law.aspx?d=79702"),
        _omitted_as_obsolete_html(print_href="LawPrint.aspx?d=79702"),
        _omitted_as_obsolete_html(
            document="<p>&sect;83. Omitted as obsolete.</p>"
        ),
        _omitted_as_obsolete_html(
            document="<p>&sect;83. Omitted as Obsolete</p>"
        ),
        _omitted_as_obsolete_html(
            document=(
                "<p>&sect;83. Omitted as obsolete</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _omitted_as_obsolete_html(include_previous=False),
        _omitted_as_obsolete_html(include_next=False),
    ],
)
def test_source_bound_omitted_as_obsolete_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=79701"
    digest = louisiana_law._EXACT_OMITTED_AS_OBSOLETE_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_dated_null_and_void() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=410448"
    evidence = louisiana_law._EXACT_DATED_NULL_AND_VOID_OFFICIAL_LOCATORS[url]
    html = _dated_null_and_void_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        louisiana_law.statute_from_law_html(
            html,
            source_url=url,
            code_name="Louisiana Revised Statutes",
        )
        is None
    )
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "null_and_void_dated"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=410448",
            "e42ac1ab9383f8fd2dfb37a11cc3311b140141150bc1b834dcd30c9f9bbd6a9a",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=410448",
            "e42ac1ab9383f8fd2dfb37a11cc3311b140141150bc1b834dcd30c9f9bbd6a9a",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=410448&copy=1",
            "e42ac1ab9383f8fd2dfb37a11cc3311b140141150bc1b834dcd30c9f9bbd6a9a",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=410448", "0" * 64),
    ],
)
def test_source_bound_dated_null_and_void_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _dated_null_and_void_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _dated_null_and_void_html(label="RS 30:2014.7"),
        _dated_null_and_void_html(label_class="law-title"),
        _dated_null_and_void_html(label_style="font-size:large;"),
        _dated_null_and_void_html(document_id="410449"),
        _dated_null_and_void_html(form_action="./Law.aspx?d=410449"),
        _dated_null_and_void_html(form_method="get"),
        _dated_null_and_void_html(form_name="lawForm"),
        _dated_null_and_void_html(print_href="LawPrint.aspx?d=410449"),
        _dated_null_and_void_html(print_target="_self"),
        _dated_null_and_void_html(print_title="Print"),
        _dated_null_and_void_html(include_previous=False),
        _dated_null_and_void_html(include_next=False),
        _dated_null_and_void_html(previous_name="previous"),
        _dated_null_and_void_html(previous_title="previous"),
        _dated_null_and_void_html(previous_type="button"),
        _dated_null_and_void_html(previous_value="<"),
        _dated_null_and_void_html(next_name="next"),
        _dated_null_and_void_html(next_title="next"),
        _dated_null_and_void_html(next_type="button"),
        _dated_null_and_void_html(next_value=">"),
    ],
)
def test_source_bound_dated_null_and_void_rejects_identity_drift(html: str) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=410448"
    digest = louisiana_law._EXACT_DATED_NULL_AND_VOID_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _dated_null_and_void_html(
            document=(
                '<div align="justify" class="A0001">'
                "&sect;2014.6. Null and void as of Jan. 1, 2009. See Acts "
                "2006, No. 779, &sect;3.</div>"
            )
        ),
        _dated_null_and_void_html(
            document=(
                '<p align="left" class="A0001">'
                "&sect;2014.6. Null and void as of Jan. 1, 2009. See Acts "
                "2006, No. 779, &sect;3.</p>"
            )
        ),
        _dated_null_and_void_html(
            document=(
                '<p align="justify" class="A0002">'
                "&sect;2014.6. Null and void as of Jan. 1, 2009. See Acts "
                "2006, No. 779, &sect;3.</p>"
            )
        ),
        _dated_null_and_void_html(
            document=(
                '<p align="justify" class="A0001">'
                "&sect;2014.7. Null and void as of Jan. 1, 2009. See Acts "
                "2006, No. 779, &sect;3.</p>"
            )
        ),
        _dated_null_and_void_html(
            document=(
                '<p align="justify" class="A0001">'
                "&sect;2014.6. Null and void as of Jan. 2, 2009. See Acts "
                "2006, No. 779, &sect;3.</p>"
            )
        ),
        _dated_null_and_void_html(
            document=(
                '<p align="justify" class="A0001">'
                "&sect;2014.6. Null and void as of Jan. 1, 2009. See Acts "
                "2006, No. 780, &sect;3.</p>"
            )
        ),
        _dated_null_and_void_html(
            document=(
                '<p align="justify" class="A0001">'
                "&sect;2014.6. Null and void as of Jan. 1, 2009. See Acts "
                "2006, No. 779, &sect;3</p>"
            )
        ),
        _dated_null_and_void_html(
            document=(
                '<p align="justify" class="A0001">'
                "&sect;2014.6. Null and void as of Jan. 1, 2009. See Acts "
                "2006, No. 779, &sect;3.</p>"
                "<p>This operative paragraph prevents terminal exclusion.</p>"
            )
        ),
    ],
)
def test_source_bound_dated_null_and_void_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=410448"
    digest = louisiana_law._EXACT_DATED_NULL_AND_VOID_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_dated_null_and_void_replays_retained_contract() -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_LA_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Louisiana acquisition evidence")

    url = "https://legis.la.gov/legis/Law.aspx?d=410448"
    evidence = louisiana_law._EXACT_DATED_NULL_AND_VOID_OFFICIAL_LOCATORS[url]
    jurisdiction_root = Path(evidence_root) / "LA"
    payload = (
        jurisdiction_root / "objects" / f'{evidence["content_sha256"]}.bin'
    ).read_bytes()
    assert len(payload) == 21_288
    assert hashlib.sha256(payload).hexdigest() == evidence["content_sha256"]
    html = payload.decode("utf-8", errors="replace")
    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "null_and_void_dated"
    )

    receipt = json.loads(
        (
            jurisdiction_root / "fetches" / f'{evidence["receipt_sha256"]}.json'
        ).read_bytes()
    )["parser_input_envelope"]["acquisition"]["receipt"]
    assert receipt["receipt_sha256"] == evidence["receipt_sha256"]
    assert receipt["receipt_cid"] == evidence["receipt_cid"]
    assert receipt["endpoint"] == url
    assert receipt["response_status"] == 200
    assert receipt["outcome_kind"] == "fetched"
    assert receipt["sanitized_request"] == {"method": "GET", "url": url}
    assert receipt["metadata"]["transport_receipt"] == {
        "content_sha256": evidence["content_sha256"],
        "official_url": url,
        "source_transport": "direct",
    }
    assert receipt["content"] == {
        "byte_size": len(payload),
        "cid": evidence["content_cid"],
        "sha256": evidence["content_sha256"],
    }


@pytest.mark.anyio
async def test_strict_frontier_closes_exact_dated_null_and_void(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=410448"
    payload = _dated_null_and_void_html().encode()
    digest = hashlib.sha256(payload).hexdigest()
    evidence = louisiana_law._EXACT_DATED_NULL_AND_VOID_OFFICIAL_LOCATORS[url]
    monkeypatch.setitem(evidence, "content_sha256", digest)

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    frontier = scraper._last_louisiana_full_frontier
    assert frontier["closed"] is True
    assert frontier["law_pages_discovered"] == 1
    assert frontier["law_pages_requested"] == 1
    assert frontier["law_pages_fetched"] == 1
    assert frontier["law_pages_classified"] == 1
    assert frontier["terminal_pages_excluded"] == 1
    assert frontier["terminal_disposition_counts"] == {"null_and_void_dated": 1}


def test_source_bound_classifier_types_exact_dated_termination() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=285631"
    evidence = louisiana_law._EXACT_DATED_TERMINATION_OFFICIAL_LOCATORS[url]
    html = _dated_termination_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "terminated"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=285631",
            "5961a2aa689afe4f6528f7711a7628a1411b97b8c185fa93ccae63ed87017216",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=285631",
            "5961a2aa689afe4f6528f7711a7628a1411b97b8c185fa93ccae63ed87017216",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=285631&copy=1",
            "5961a2aa689afe4f6528f7711a7628a1411b97b8c185fa93ccae63ed87017216",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=285631", "0" * 64),
    ],
)
def test_source_bound_dated_termination_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _dated_termination_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _dated_termination_html(label="RS 17:85.10"),
        _dated_termination_html(document_id="285632"),
        _dated_termination_html(form_action="./Law.aspx?d=285632"),
        _dated_termination_html(print_href="LawPrint.aspx?d=285632"),
        _dated_termination_html(
            document=(
                "<p>&sect;85.9. Terminated on Dec. 31, 2004, by Acts 2004, "
                "No. 563, &sect;3, eff. July 6, 2004</p>"
            )
        ),
        _dated_termination_html(
            document=(
                "<p>&sect;85.9. Terminated on December 31, 2004, by Acts "
                "2004, No. 563, &sect;3, eff. July 6, 2004.</p>"
            )
        ),
        _dated_termination_html(
            document=(
                "<p>&sect;85.9. Terminated on Dec. 31, 2004, by Acts 2004, "
                "No. 563, &sect;3, eff. July 6, 2004.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _dated_termination_html(include_previous=False),
        _dated_termination_html(include_next=False),
    ],
)
def test_source_bound_dated_termination_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=285631"
    digest = louisiana_law._EXACT_DATED_TERMINATION_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_second_exact_dated_termination() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=285632"
    evidence = louisiana_law._EXACT_DATED_TERMINATION_OFFICIAL_LOCATORS[url]
    html = _dated_termination_85_10_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "terminated"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=285632",
            "d468d444729607a8cae1f029d7e0258e86b06ff119b77f80dd20b46f5895a2b3",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=285632",
            "d468d444729607a8cae1f029d7e0258e86b06ff119b77f80dd20b46f5895a2b3",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=285632&copy=1",
            "d468d444729607a8cae1f029d7e0258e86b06ff119b77f80dd20b46f5895a2b3",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=285632", "0" * 64),
    ],
)
def test_source_bound_second_dated_termination_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _dated_termination_85_10_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _dated_termination_85_10_html(label="RS 17:85.11"),
        _dated_termination_85_10_html(document_id="285633"),
        _dated_termination_85_10_html(form_action="./Law.aspx?d=285633"),
        _dated_termination_85_10_html(print_href="LawPrint.aspx?d=285633"),
        _dated_termination_85_10_html(
            document=(
                "<p>&sect;85.10. Terminated on Dec. 31, 2004, by Acts 2004, "
                "No. 718, &sect;3, eff. July 6, 2004</p>"
            )
        ),
        _dated_termination_85_10_html(
            document=(
                "<p>&sect;85.10. Terminated on December 31, 2004, by Acts "
                "2004, No. 718, &sect;3, eff. July 6, 2004.</p>"
            )
        ),
        _dated_termination_85_10_html(
            document=(
                "<p>&sect;85.10. Terminated on Dec. 31, 2004, by Acts 2004, "
                "No. 718, &sect;3, eff. July 6, 2004.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _dated_termination_85_10_html(include_previous=False),
        _dated_termination_85_10_html(include_next=False),
    ],
)
def test_source_bound_second_dated_termination_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=285632"
    digest = louisiana_law._EXACT_DATED_TERMINATION_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_title_23_dated_termination() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=409787"
    evidence = louisiana_law._EXACT_DATED_TERMINATION_OFFICIAL_LOCATORS[url]
    html = _dated_termination_23_1020_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "terminated"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=409787",
            "5556a54ffd05e1a7788b50de56e0d174472d9e47e81229937151bf4182a5ab76",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=409787",
            "5556a54ffd05e1a7788b50de56e0d174472d9e47e81229937151bf4182a5ab76",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=409787&copy=1",
            "5556a54ffd05e1a7788b50de56e0d174472d9e47e81229937151bf4182a5ab76",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=409787", "0" * 64),
    ],
)
def test_source_bound_title_23_dated_termination_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _dated_termination_23_1020_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _dated_termination_23_1020_html(label="RS 23:1020.1"),
        _dated_termination_23_1020_html(document_id="409788"),
        _dated_termination_23_1020_html(form_action="./Law.aspx?d=409788"),
        _dated_termination_23_1020_html(print_href="LawPrint.aspx?d=409788"),
        _dated_termination_23_1020_html(
            document=(
                "<p>CHAPTER 10. WORKERS' COMPENSATION</p>"
                "<p>PART II. SCOPE AND OPERATION</p>"
                "<p>SUBPART A. DEFINITIONS</p>"
                "<p>&sect;1020. Terminated on June 30, 2006, by Acts 2006, "
                "No. 193, eff. June 2, 2006.</p>"
            )
        ),
        _dated_termination_23_1020_html(
            document=(
                "<p>CHAPTER 10. WORKERS' COMPENSATION</p>"
                "<p>PART I. SCOPE AND OPERATION</p>"
                "<p>SUBPART A. DEFINITIONS</p>"
                "<p>&sect;1020. Terminated on June 30, 2006, by Acts 2006, "
                "No. 194, eff. June 2, 2006.</p>"
            )
        ),
        _dated_termination_23_1020_html(
            document=(
                "<p>CHAPTER 10. WORKERS' COMPENSATION</p>"
                "<p>PART I. SCOPE AND OPERATION</p>"
                "<p>SUBPART A. DEFINITIONS</p>"
                "<p>&sect;1020. Terminated on June 30, 2006, by Acts 2006, "
                "No. 193, eff. June 2, 2006.</p>"
                "<p>Operative text prevents terminal exclusion.</p>"
            )
        ),
        _dated_termination_23_1020_html(include_previous=False),
        _dated_termination_23_1020_html(include_next=False),
    ],
)
def test_source_bound_title_23_dated_termination_rejects_identity_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=409787"
    digest = louisiana_law._EXACT_DATED_TERMINATION_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_title_23_dated_termination_matches_retained_contracts() -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_LA_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Louisiana acquisition evidence")

    url = "https://legis.la.gov/legis/Law.aspx?d=409787"
    evidence = louisiana_law._EXACT_DATED_TERMINATION_OFFICIAL_LOCATORS[url]
    jurisdiction_root = Path(evidence_root) / "LA"
    payload = (
        jurisdiction_root / "objects" / f'{evidence["content_sha256"]}.bin'
    ).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == evidence["content_sha256"]
    html = payload.decode("utf-8", errors="replace")
    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "terminated"
    )

    toc_receipt_path = (
        jurisdiction_root
        / "fetches"
        / f'{evidence["toc_receipt_sha256"]}.json'
    )
    toc_receipt_bytes = toc_receipt_path.read_bytes()
    toc_receipt = json.loads(toc_receipt_bytes)
    assert toc_receipt["parser_input_envelope"]["acquisition"]["receipt"][
        "receipt_sha256"
    ] == evidence["toc_receipt_sha256"]
    toc_content = toc_receipt["parser_input_envelope"]["acquisition"]["receipt"][
        "content"
    ]
    assert toc_content["sha256"] == evidence["toc_content_sha256"]
    toc_payload = (
        jurisdiction_root / "objects" / f'{evidence["toc_content_sha256"]}.bin'
    ).read_bytes()
    assert hashlib.sha256(toc_payload).hexdigest() == evidence["toc_content_sha256"]

    from bs4 import BeautifulSoup

    toc = BeautifulSoup(toc_payload, "html.parser")
    links = [
        link
        for link in toc.find_all("a", href=True)
        if "Law.aspx?d=" in str(link.get("href") or "")
    ]
    label_link = next(
        link
        for link in links
        if str(link.get("href") or "") == "Law.aspx?d=409787"
        and link.get_text(" ", strip=True) == evidence["toc_label"]
    )
    label_index = links.index(label_link)
    assert links[label_index + 1].get_text(" ", strip=True) == evidence["toc_caption"]
    assert links[label_index - 2].get_text(" ", strip=True) == evidence[
        "toc_previous_label"
    ]
    assert links[label_index + 2].get_text(" ", strip=True) == evidence[
        "toc_next_label"
    ]


@pytest.mark.anyio
async def test_strict_frontier_closes_retained_title_23_dated_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_LA_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Louisiana acquisition evidence")

    url = "https://legis.la.gov/legis/Law.aspx?d=409787"
    evidence = louisiana_law._EXACT_DATED_TERMINATION_OFFICIAL_LOCATORS[url]
    payload = (
        Path(evidence_root)
        / "LA"
        / "objects"
        / f'{evidence["content_sha256"]}.bin'
    ).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == evidence["content_sha256"]

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    frontier = scraper._last_louisiana_full_frontier
    assert frontier["closed"] is True
    assert frontier["law_pages_discovered"] == 1
    assert frontier["law_pages_requested"] == 1
    assert frontier["law_pages_fetched"] == 1
    assert frontier["law_pages_classified"] == 1
    assert frontier["terminal_pages_excluded"] == 1
    assert frontier["terminal_disposition_counts"] == {"terminated": 1}


def test_source_bound_classifier_types_exact_wrapped_title_25_heading() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=84265"
    evidence = louisiana_law._EXACT_WRAPPED_TITLE_HEADING_OFFICIAL_LOCATORS[url]
    html = _wrapped_title_25_heading_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "title_heading"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=84265",
            "33768bbfd907447e73e035138ac74e3953ebaaa8c8b46e79b6348fb649c902f0",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=84265",
            "33768bbfd907447e73e035138ac74e3953ebaaa8c8b46e79b6348fb649c902f0",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=84265&copy=1",
            "33768bbfd907447e73e035138ac74e3953ebaaa8c8b46e79b6348fb649c902f0",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=84265", "0" * 64),
    ],
)
def test_source_bound_wrapped_title_25_heading_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _wrapped_title_25_heading_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _wrapped_title_25_heading_html(label="RS 25A"),
        _wrapped_title_25_heading_html(document_id="84266"),
        _wrapped_title_25_heading_html(form_action="./Law.aspx?d=84266"),
        _wrapped_title_25_heading_html(form_method="get"),
        _wrapped_title_25_heading_html(print_href="LawPrint.aspx?d=84266"),
        _wrapped_title_25_heading_html(print_target="_self"),
        _wrapped_title_25_heading_html(print_title="Print"),
        _wrapped_title_25_heading_html(previous_name="previous"),
        _wrapped_title_25_heading_html(previous_title="previous"),
        _wrapped_title_25_heading_html(previous_type="button"),
        _wrapped_title_25_heading_html(previous_value="previous"),
        _wrapped_title_25_heading_html(next_name="next"),
        _wrapped_title_25_heading_html(next_title="next"),
        _wrapped_title_25_heading_html(next_type="button"),
        _wrapped_title_25_heading_html(next_value="next"),
        _wrapped_title_25_heading_html(
            document=(
                '<p class="A0001">TITLE 25. LIBRARIES, MUSEUMS, AND OTHER '
                "SCIENTIFIC AND CULTURAL FACILITIES</p>"
            )
        ),
        _wrapped_title_25_heading_html(
            document=(
                '<p class="A0001">TITLE 25. LIBRARIES, MUSEUMS, AND OTHER '
                "SCIENCES</p>"
                '<p class="A0001">AND CULTURAL FACILITIES</p>'
            )
        ),
        _wrapped_title_25_heading_html(
            document=(
                '<p class="A0001">TITLE 25. LIBRARIES, MUSEUMS, AND OTHER '
                "SCIENTIFIC</p>"
                '<p class="A0001">AND CULTURAL FACILITY</p>'
            )
        ),
        _wrapped_title_25_heading_html(
            document=(
                '<p class="A0001">TITLE 25. LIBRARIES, MUSEUMS, AND OTHER '
                "SCIENTIFIC</p>"
                '<p class="A0001">AND CULTURAL FACILITIES</p>'
                "<p>Operative text prevents terminal exclusion.</p>"
            )
        ),
        _wrapped_title_25_heading_html(include_previous=False),
        _wrapped_title_25_heading_html(include_next=False),
    ],
)
def test_source_bound_wrapped_title_25_heading_rejects_identity_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=84265"
    digest = louisiana_law._EXACT_WRAPPED_TITLE_HEADING_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_wrapped_title_25_heading_matches_retained_contracts() -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_LA_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Louisiana acquisition evidence")

    url = "https://legis.la.gov/legis/Law.aspx?d=84265"
    evidence = louisiana_law._EXACT_WRAPPED_TITLE_HEADING_OFFICIAL_LOCATORS[url]
    jurisdiction_root = Path(evidence_root) / "LA"
    payload = (
        jurisdiction_root / "objects" / f'{evidence["content_sha256"]}.bin'
    ).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == evidence["content_sha256"]
    html = payload.decode("utf-8", errors="replace")
    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "title_heading"
    )

    body_receipt = json.loads(
        (
            jurisdiction_root
            / "fetches"
            / f'{evidence["receipt_sha256"]}.json'
        ).read_bytes()
    )["parser_input_envelope"]["acquisition"]["receipt"]
    assert body_receipt["receipt_sha256"] == evidence["receipt_sha256"]
    assert body_receipt["receipt_cid"] == evidence["receipt_cid"]
    assert body_receipt["endpoint"] == url
    assert body_receipt["response_status"] == 200
    assert body_receipt["content"] == {
        "byte_size": len(payload),
        "cid": evidence["content_cid"],
        "sha256": evidence["content_sha256"],
    }

    toc_receipt = json.loads(
        (
            jurisdiction_root
            / "fetches"
            / f'{evidence["toc_receipt_sha256"]}.json'
        ).read_bytes()
    )["parser_input_envelope"]["acquisition"]["receipt"]
    assert toc_receipt["receipt_sha256"] == evidence["toc_receipt_sha256"]
    assert toc_receipt["receipt_cid"] == evidence["toc_receipt_cid"]
    assert toc_receipt["endpoint"] == evidence["toc_endpoint"]
    assert toc_receipt["sanitized_request"]["method"] == evidence[
        "toc_request_method"
    ]
    assert toc_receipt["sanitized_request"]["request_body_sha256"] == evidence[
        "toc_request_body_sha256"
    ]
    assert toc_receipt["pagination"] == {
        "kind": "aspnet_postback",
        "page_count": evidence["toc_page_count"],
        "page_index": evidence["toc_page_index"],
    }
    toc_payload = (
        jurisdiction_root / "objects" / f'{evidence["toc_content_sha256"]}.bin'
    ).read_bytes()
    assert hashlib.sha256(toc_payload).hexdigest() == evidence["toc_content_sha256"]
    assert toc_receipt["content"] == {
        "byte_size": len(toc_payload),
        "cid": evidence["toc_content_cid"],
        "sha256": evidence["toc_content_sha256"],
    }

    from bs4 import BeautifulSoup

    toc = BeautifulSoup(toc_payload, "html.parser")
    links = [
        link
        for link in toc.find_all("a", href=True)
        if "Law.aspx?d=" in str(link.get("href") or "")
    ]
    assert str(links[0].get("href") or "") == "Law.aspx?d=84265"
    assert links[0].get_text(" ", strip=True) == evidence["toc_label"]
    assert str(links[1].get("href") or "") == "Law.aspx?d=84265"
    assert links[1].get_text(" ", strip=True) == evidence["toc_caption"]
    assert str(links[2].get("href") or "") == "Law.aspx?d=84266"
    assert links[2].get_text(" ", strip=True) == evidence["toc_next_label"]
    assert str(links[3].get("href") or "") == "Law.aspx?d=84266"
    assert links[3].get_text(" ", strip=True) == evidence["toc_next_caption"]


@pytest.mark.anyio
async def test_strict_frontier_closes_retained_wrapped_title_25_heading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_LA_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Louisiana acquisition evidence")

    url = "https://legis.la.gov/legis/Law.aspx?d=84265"
    evidence = louisiana_law._EXACT_WRAPPED_TITLE_HEADING_OFFICIAL_LOCATORS[url]
    payload = (
        Path(evidence_root)
        / "LA"
        / "objects"
        / f'{evidence["content_sha256"]}.bin'
    ).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == evidence["content_sha256"]

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    frontier = scraper._last_louisiana_full_frontier
    assert frontier["closed"] is True
    assert frontier["law_pages_discovered"] == 1
    assert frontier["law_pages_requested"] == 1
    assert frontier["law_pages_fetched"] == 1
    assert frontier["law_pages_classified"] == 1
    assert frontier["terminal_pages_excluded"] == 1
    assert frontier["terminal_disposition_counts"] == {"title_heading": 1}


def test_source_bound_classifier_types_exact_range_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81194"
    evidence = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    html = _range_redesignation_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_range"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=81194",
            "b705d5f62053f2de2bb387d632f7650201b6c85de25a6581db3e9242be9b475d",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=81194",
            "b705d5f62053f2de2bb387d632f7650201b6c85de25a6581db3e9242be9b475d",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=81194&copy=1",
            "b705d5f62053f2de2bb387d632f7650201b6c85de25a6581db3e9242be9b475d",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=81194", "0" * 64),
    ],
)
def test_source_bound_range_redesignation_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _range_redesignation_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _range_redesignation_html(label="RS 17:772"),
        _range_redesignation_html(document_id="81195"),
        _range_redesignation_html(form_action="./Law.aspx?d=81195"),
        _range_redesignation_html(print_href="LawPrint.aspx?d=81195"),
        _range_redesignation_html(
            document=(
                "<p>PART VIII. OPTIONAL RETIREMENT PLAN FOR ACADEMIC</p>"
                "<p>AND ADMINISTRATIVE EMPLOYEES OF PUBLIC</p>"
                "<p>INSTITUTIONS OF HIGHER EDUCATION</p>"
                "<p>&sect;771. &sect;&sect;771 to 781 redesignated as R.S. "
                "11:921 to 931 by Acts 1991, No. 74, &sect;3.</p>"
            )
        ),
        _range_redesignation_html(
            document=(
                "<p>PART VII. OPTIONAL RETIREMENT PLAN FOR ACADEMIC</p>"
                "<p>AND ADMINISTRATIVE EMPLOYEES OF PUBLIC</p>"
                "<p>INSTITUTIONS OF HIGHER EDUCATION</p>"
                "<p>&sect;771. &sect;&sect;771 to 782 redesignated as R.S. "
                "11:921 to 931 by Acts 1991, No. 74, &sect;3.</p>"
            )
        ),
        _range_redesignation_html(
            document=(
                "<p>PART VII. OPTIONAL RETIREMENT PLAN FOR ACADEMIC</p>"
                "<p>AND ADMINISTRATIVE EMPLOYEES OF PUBLIC</p>"
                "<p>INSTITUTIONS OF HIGHER EDUCATION</p>"
                "<p>&sect;771. &sect;&sect;771 to 781 redesignated as R.S. "
                "11:922 to 932 by Acts 1991, No. 74, &sect;3.</p>"
            )
        ),
        _range_redesignation_html(
            document=(
                "<p>PART VII. OPTIONAL RETIREMENT PLAN FOR ACADEMIC</p>"
                "<p>AND ADMINISTRATIVE EMPLOYEES OF PUBLIC</p>"
                "<p>INSTITUTIONS OF HIGHER EDUCATION</p>"
                "<p>&sect;771. &sect;&sect;771 to 781 redesignated as R.S. "
                "11:921 to 931 by Acts 1991, No. 74, &sect;3.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _range_redesignation_html(include_previous=False),
        _range_redesignation_html(include_next=False),
    ],
)
def test_source_bound_range_redesignation_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81194"
    digest = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_chapter_wrapped_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=89224"
    evidence = (
        louisiana_law._EXACT_CHAPTER_WRAPPED_REDESIGNATION_OFFICIAL_LOCATORS[url]
    )
    html = _chapter_wrapped_redesignation_html()

    assert terminal_disposition_from_law_html(html) == "redesignated"
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_chapter_wrapper"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=89224",
            "a3111e4353d160641af9c069e62b5cf996cddc0927055532625526439be7b9cf",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=89224",
            "a3111e4353d160641af9c069e62b5cf996cddc0927055532625526439be7b9cf",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=89224&copy=1",
            "a3111e4353d160641af9c069e62b5cf996cddc0927055532625526439be7b9cf",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=89224", "0" * 64),
    ],
)
def test_source_bound_chapter_wrapped_redesignation_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _chapter_wrapped_redesignation_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _chapter_wrapped_redesignation_html(label="RS 33:1422"),
        _chapter_wrapped_redesignation_html(document_id="89225"),
        _chapter_wrapped_redesignation_html(form_action="./Law.aspx?d=89225"),
        _chapter_wrapped_redesignation_html(form_method="get"),
        _chapter_wrapped_redesignation_html(form_name="changedForm"),
        _chapter_wrapped_redesignation_html(print_href="LawPrint.aspx?d=89225"),
        _chapter_wrapped_redesignation_html(print_target="_self"),
        _chapter_wrapped_redesignation_html(print_title="Changed"),
        _chapter_wrapped_redesignation_html(
            document=(
                '<p class="A0001"><br /></p>'
                '<p class="A0001"><br /></p>'
                '<p class="A0002" align="center">'
                "CHAPTER 3. PUBLIC OFFICERS</p>"
                '<p class="A0002" align="center">'
                "(REDESIGNATED AS CHAPTER 36 OF TITLE 13)</p>"
                '<p class="A0002" align="justify">&sect;1421. Redesignated '
                "as R.S. 13:5521 pursuant to Acts 2011, No. 248, &sect;3.</p>"
            )
        ),
        _chapter_wrapped_redesignation_html(
            document=(
                '<p class="A0001"><br /></p>'
                '<p class="A0001"><br /></p>'
                '<p class="A0002" align="center">'
                "CHAPTER 3. PUBLIC OFFICERS</p>"
                '<p class="A0002" align="center">'
                "(REDESIGNATED AS CHAPTER 35 OF TITLE 13)</p>"
                '<p class="A0002" align="justify">&sect;1421. Redesignated '
                "as R.S. 13:5522 pursuant to Acts 2011, No. 248, &sect;3.</p>"
            )
        ),
        _chapter_wrapped_redesignation_html(
            document=(
                '<p class="A0001"><br /></p>'
                '<p class="A0001"><br /></p>'
                '<p class="A0002" align="center">'
                "CHAPTER 3. PUBLIC OFFICERS</p>"
                '<p class="A0002" align="center">'
                "(REDESIGNATED AS CHAPTER 35 OF TITLE 13)</p>"
                '<p class="A0002" align="justify">&sect;1421. Redesignated '
                "as R.S. 13:5521 pursuant to Acts 2011, No. 248, &sect;3.</p>"
                "<p>This operative paragraph prevents exclusion.</p>"
            )
        ),
        _chapter_wrapped_redesignation_html(include_previous=False),
        _chapter_wrapped_redesignation_html(include_next=False),
    ],
)
def test_source_bound_chapter_wrapped_redesignation_rejects_dom_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=89224"
    digest = louisiana_law._EXACT_CHAPTER_WRAPPED_REDESIGNATION_OFFICIAL_LOCATORS[
        url
    ]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_second_exact_range_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81224"
    evidence = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    html = _range_redesignation_17_881_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_range"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=81224",
            "be51153efa5fa22b2ceba9b2ff453882dc4834135c298c0b33c22c1201be9ca5",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=81224",
            "be51153efa5fa22b2ceba9b2ff453882dc4834135c298c0b33c22c1201be9ca5",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=81224&copy=1",
            "be51153efa5fa22b2ceba9b2ff453882dc4834135c298c0b33c22c1201be9ca5",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=81224", "0" * 64),
    ],
)
def test_source_bound_second_range_redesignation_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _range_redesignation_17_881_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _range_redesignation_17_881_html(label="RS 17:882"),
        _range_redesignation_17_881_html(document_id="81225"),
        _range_redesignation_17_881_html(form_action="./Law.aspx?d=81225"),
        _range_redesignation_17_881_html(print_href="LawPrint.aspx?d=81225"),
        _range_redesignation_17_881_html(
            document=(
                "<p>PART IX. STATE-SCHOOL EMPLOYEES RETIREMENT SYSTEM</p>"
                "<p>&sect;881. &sect;&sect;881 to 994 redesignated as R.S. "
                "11:1001 to 1204 by Acts 1991, No. 74, &sect;3.</p>"
            )
        ),
        _range_redesignation_17_881_html(
            document=(
                "<p>PART VIII. STATE-SCHOOL EMPLOYEES RETIREMENT SYSTEM</p>"
                "<p>&sect;881. &sect;&sect;881 to 995 redesignated as R.S. "
                "11:1001 to 1204 by Acts 1991, No. 74, &sect;3.</p>"
            )
        ),
        _range_redesignation_17_881_html(
            document=(
                "<p>PART VIII. STATE-SCHOOL EMPLOYEES RETIREMENT SYSTEM</p>"
                "<p>&sect;881. &sect;&sect;881 to 994 redesignated as R.S. "
                "11:1002 to 1205 by Acts 1991, No. 74, &sect;3.</p>"
            )
        ),
        _range_redesignation_17_881_html(
            document=(
                "<p>PART VIII. STATE-SCHOOL EMPLOYEES RETIREMENT SYSTEM</p>"
                "<p>&sect;881. &sect;&sect;881 to 994 redesignated as R.S. "
                "11:1001 to 1204 by Acts 1991, No. 75, &sect;3.</p>"
            )
        ),
        _range_redesignation_17_881_html(
            document=(
                "<p>PART VIII. STATE-SCHOOL EMPLOYEES RETIREMENT SYSTEM</p>"
                "<p>&sect;881. &sect;&sect;881 to 994 redesignated as R.S. "
                "11:1001 to 1204 by Acts 1991, No. 74, &sect;3.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _range_redesignation_17_881_html(include_previous=False),
        _range_redesignation_17_881_html(include_next=False),
    ],
)
def test_source_bound_second_range_redesignation_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81224"
    digest = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_third_exact_range_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=79745"
    evidence = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    html = _range_redesignation_17_1011_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_range"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=79745",
            "fcfb2096a78b6741236e605d92552f05a461825648dee74063cb3fd05df5fb8f",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=79745",
            "fcfb2096a78b6741236e605d92552f05a461825648dee74063cb3fd05df5fb8f",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=79745&copy=1",
            "fcfb2096a78b6741236e605d92552f05a461825648dee74063cb3fd05df5fb8f",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=79745", "0" * 64),
    ],
)
def test_source_bound_third_range_redesignation_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _range_redesignation_17_1011_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _range_redesignation_17_1011_html(label="RS 17:1012"),
        _range_redesignation_17_1011_html(document_id="79746"),
        _range_redesignation_17_1011_html(form_action="./Law.aspx?d=79746"),
        _range_redesignation_17_1011_html(print_href="LawPrint.aspx?d=79746"),
        _range_redesignation_17_1011_html(
            document=(
                "<p>PART X. ORLEANS PARISH SCHOOL EMPLOYEES</p>"
                "<p>RETIREMENT SYSTEM</p>"
                "<p>SUBPART A. GENERAL PROVISIONS</p>"
                "<p>&sect;1011-1128. Redesignated as R.S. 11:951.1-951.88 "
                "pursuant to R.S. 24:253.</p>"
            )
        ),
        _range_redesignation_17_1011_html(
            document=(
                "<p>PART IX. ORLEANS PARISH SCHOOL EMPLOYEES</p>"
                "<p>RETIREMENT SYSTEM</p>"
                "<p>SUBPART B. GENERAL PROVISIONS</p>"
                "<p>&sect;1011-1128. Redesignated as R.S. 11:951.1-951.88 "
                "pursuant to R.S. 24:253.</p>"
            )
        ),
        _range_redesignation_17_1011_html(
            document=(
                "<p>PART IX. ORLEANS PARISH SCHOOL EMPLOYEES</p>"
                "<p>RETIREMENT SYSTEM</p>"
                "<p>SUBPART A. GENERAL PROVISIONS</p>"
                "<p>&sect;1011-1129. Redesignated as R.S. 11:951.1-951.88 "
                "pursuant to R.S. 24:253.</p>"
            )
        ),
        _range_redesignation_17_1011_html(
            document=(
                "<p>PART IX. ORLEANS PARISH SCHOOL EMPLOYEES</p>"
                "<p>RETIREMENT SYSTEM</p>"
                "<p>SUBPART A. GENERAL PROVISIONS</p>"
                "<p>&sect;1011-1128. Redesignated as R.S. 11:951.1-951.89 "
                "pursuant to R.S. 24:253.</p>"
            )
        ),
        _range_redesignation_17_1011_html(
            document=(
                "<p>PART IX. ORLEANS PARISH SCHOOL EMPLOYEES</p>"
                "<p>RETIREMENT SYSTEM</p>"
                "<p>SUBPART A. GENERAL PROVISIONS</p>"
                "<p>&sect;1011-1128. Redesignated as R.S. 11:951.1-951.88 "
                "pursuant to R.S. 24:254.</p>"
            )
        ),
        _range_redesignation_17_1011_html(
            document=(
                "<p>PART IX. ORLEANS PARISH SCHOOL EMPLOYEES</p>"
                "<p>RETIREMENT SYSTEM</p>"
                "<p>SUBPART A. GENERAL PROVISIONS</p>"
                "<p>&sect;1011-1128. Redesignated as R.S. 11:951.1-951.88 "
                "pursuant to R.S. 24:253.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _range_redesignation_17_1011_html(include_previous=False),
        _range_redesignation_17_1011_html(include_next=False),
    ],
)
def test_source_bound_third_range_redesignation_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=79745"
    digest = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_fourth_exact_range_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81494"
    evidence = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    html = _range_redesignation_18_1651_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_range"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=81494",
            "6a6bb2355b6d6ebc868bc6bf48ecd36413dc30d35bcd64123f10fea5fab77d7a",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=81494",
            "6a6bb2355b6d6ebc868bc6bf48ecd36413dc30d35bcd64123f10fea5fab77d7a",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=81494&copy=1",
            "6a6bb2355b6d6ebc868bc6bf48ecd36413dc30d35bcd64123f10fea5fab77d7a",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=81494", "0" * 64),
    ],
)
def test_source_bound_fourth_range_redesignation_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _range_redesignation_18_1651_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _range_redesignation_18_1651_html(label="RS 18:1652"),
        _range_redesignation_18_1651_html(document_id="81495"),
        _range_redesignation_18_1651_html(form_action="./Law.aspx?d=81495"),
        _range_redesignation_18_1651_html(print_href="LawPrint.aspx?d=81495"),
        _range_redesignation_18_1651_html(
            document=(
                "<p>CHAPTER 13. &nbsp;REGISTRARS OF VOTERS</p>"
                "<p>EMPLOYEES' RETIREMENT SYSTEM</p>"
                "<p>&sect;1651. &nbsp;&sect;&sect;1651 to 1844 redesignated by "
                "Acts 1991, No. 74, &sect;3. &nbsp;See, now, Title 11.</p>"
            )
        ),
        _range_redesignation_18_1651_html(
            document=(
                "<p>CHAPTER 12. &nbsp;REGISTRARS OF VOTERS</p>"
                "<p>EMPLOYEES' PENSION SYSTEM</p>"
                "<p>&sect;1651. &nbsp;&sect;&sect;1651 to 1844 redesignated by "
                "Acts 1991, No. 74, &sect;3. &nbsp;See, now, Title 11.</p>"
            )
        ),
        _range_redesignation_18_1651_html(
            document=(
                "<p>CHAPTER 12. &nbsp;REGISTRARS OF VOTERS</p>"
                "<p>EMPLOYEES' RETIREMENT SYSTEM</p>"
                "<p>&sect;1651. &nbsp;&sect;&sect;1651 to 1845 redesignated by "
                "Acts 1991, No. 74, &sect;3. &nbsp;See, now, Title 11.</p>"
            )
        ),
        _range_redesignation_18_1651_html(
            document=(
                "<p>CHAPTER 12. &nbsp;REGISTRARS OF VOTERS</p>"
                "<p>EMPLOYEES' RETIREMENT SYSTEM</p>"
                "<p>&sect;1651. &nbsp;&sect;&sect;1651 to 1844 redesignated by "
                "Acts 1991, No. 75, &sect;3. &nbsp;See, now, Title 11.</p>"
            )
        ),
        _range_redesignation_18_1651_html(
            document=(
                "<p>CHAPTER 12. &nbsp;REGISTRARS OF VOTERS</p>"
                "<p>EMPLOYEES' RETIREMENT SYSTEM</p>"
                "<p>&sect;1651. &nbsp;&sect;&sect;1651 to 1844 redesignated by "
                "Acts 1991, No. 74, &sect;3. &nbsp;See, now, Title 12.</p>"
            )
        ),
        _range_redesignation_18_1651_html(
            document=(
                "<p>CHAPTER 12. &nbsp;REGISTRARS OF VOTERS</p>"
                "<p>EMPLOYEES' RETIREMENT SYSTEM</p>"
                "<p>&sect;1651. &nbsp;&sect;&sect;1651 to 1844 redesignated by "
                "Acts 1991, No. 74, &sect;3. &nbsp;See, now, Title 11.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _range_redesignation_18_1651_html(include_previous=False),
        _range_redesignation_18_1651_html(include_next=False),
    ],
)
def test_source_bound_fourth_range_redesignation_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81494"
    digest = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_title_29_range_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85614"
    evidence = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    html = _range_redesignation_29_461_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_range"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256", "html"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=85614",
            "52d0e48343c4d4576ab6800207411e1a1cf41290a8bb95b4a823064a439425e1",
            _range_redesignation_29_461_html(),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85614",
            "0" * 64,
            _range_redesignation_29_461_html(),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85614",
            "52d0e48343c4d4576ab6800207411e1a1cf41290a8bb95b4a823064a439425e1",
            _range_redesignation_29_461_html(label="RS 29:462"),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85614",
            "52d0e48343c4d4576ab6800207411e1a1cf41290a8bb95b4a823064a439425e1",
            _range_redesignation_29_461_html(label_class="heading"),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85614",
            "52d0e48343c4d4576ab6800207411e1a1cf41290a8bb95b4a823064a439425e1",
            _range_redesignation_29_461_html(form_method="get"),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85614",
            "52d0e48343c4d4576ab6800207411e1a1cf41290a8bb95b4a823064a439425e1",
            _range_redesignation_29_461_html(previous_title="previous law"),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85614",
            "52d0e48343c4d4576ab6800207411e1a1cf41290a8bb95b4a823064a439425e1",
            _range_redesignation_29_461_html(
                document=(
                    '<p align="center" class="A0001">PART II. PENSIONS</p>'
                    '<p align="justify" class="A0003">&sect;461. '
                    "&sect;&sect;461 to 468 Redesignated as R.S. 11:1391 to "
                    "1397 by Acts 1991, No. 74, &sect;1.</p>"
                )
            ),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85614",
            "52d0e48343c4d4576ab6800207411e1a1cf41290a8bb95b4a823064a439425e1",
            _range_redesignation_29_461_html(
                document=(
                    '<p align="center" class="A0001">PART II. PENSIONS</p>'
                    '<p align="justify" class="A0002">&sect;461. '
                    "&sect;&sect;461 to 469 Redesignated as R.S. 11:1391 to "
                    "1397 by Acts 1991, No. 74, &sect;1.</p>"
                )
            ),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=85614",
            "52d0e48343c4d4576ab6800207411e1a1cf41290a8bb95b4a823064a439425e1",
            _range_redesignation_29_461_html(
                document=(
                    '<p align="center" class="A0001">PART II. PENSIONS</p>'
                    '<p align="justify" class="A0002">&sect;461. '
                    "&sect;&sect;461 to 468 Redesignated as R.S. 11:1391 to "
                    "1397 by Acts 1991, No. 74, &sect;1.</p>"
                    "<p>Operative text prevents terminal exclusion.</p>"
                )
            ),
        ),
    ],
)
def test_source_bound_title_29_range_redesignation_rejects_drift(
    source_url: str,
    content_sha256: str,
    html: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


def test_source_bound_classifier_types_exact_title_30_range_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=86914"
    evidence = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    html = _range_redesignation_30_1051_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_range"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256", "html"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=86914",
            "f25964dc56625041c3aafa183795913e7ae0b44ed02df33265b31101ec36b962",
            _range_redesignation_30_1051_html(),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=86914",
            "0" * 64,
            _range_redesignation_30_1051_html(),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=86914",
            "f25964dc56625041c3aafa183795913e7ae0b44ed02df33265b31101ec36b962",
            _range_redesignation_30_1051_html(label="RS 30:1052"),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=86914",
            "f25964dc56625041c3aafa183795913e7ae0b44ed02df33265b31101ec36b962",
            _range_redesignation_30_1051_html(
                document=(
                    '<p align="center" class="A0001">CHAPTER 11. '
                    "ENVIRONMENTAL QUALITY</p>"
                    '<p align="justify" class="A0002">&sect;1051. '
                    "&sect;&sect;1051 to 1150.96 redesignated as Subtitle II "
                    "of Title 30 (R.S. 30:2001 to 2396)</p>"
                )
            ),
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=86914",
            "f25964dc56625041c3aafa183795913e7ae0b44ed02df33265b31101ec36b962",
            _range_redesignation_30_1051_html(
                document=(
                    '<p align="center" class="A0001">CHAPTER 11. '
                    "ENVIRONMENTAL QUALITY</p>"
                    '<p align="justify" class="A0002">&sect;1051. '
                    "&sect;&sect;1051 to 1150 .96 redesignated as Subtitle II "
                    "of Title 30 (R.S. 30:2001 to 2396)</p>"
                    "<p>Operative text prevents terminal exclusion.</p>"
                )
            ),
        ),
    ],
)
def test_source_bound_title_30_range_redesignation_rejects_drift(
    source_url: str,
    content_sha256: str,
    html: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


def test_source_bound_classifier_types_exact_to_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81535"
    evidence = louisiana_law._EXACT_TO_REDESIGNATION_OFFICIAL_LOCATORS[url]
    html = _to_redesignation_18_221_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_to"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=81535",
            "2d1ce863e326ba4fc80fc9157e3bc4b954c7c86b302f80cf10c44ed24c715ce4",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=81535",
            "2d1ce863e326ba4fc80fc9157e3bc4b954c7c86b302f80cf10c44ed24c715ce4",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=81535&copy=1",
            "2d1ce863e326ba4fc80fc9157e3bc4b954c7c86b302f80cf10c44ed24c715ce4",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=81535", "0" * 64),
    ],
)
def test_source_bound_to_redesignation_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _to_redesignation_18_221_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _to_redesignation_18_221_html(label="RS 18:222"),
        _to_redesignation_18_221_html(document_id="81536"),
        _to_redesignation_18_221_html(form_action="./Law.aspx?d=81536"),
        _to_redesignation_18_221_html(print_href="LawPrint.aspx?d=81536"),
        _to_redesignation_18_221_html(
            document=(
                "<p>&sect;221. Redesignated to R.S. 18:67 by Acts 2017, "
                "No. 176, &sect;6, eff. June 14, 2017.</p>"
            )
        ),
        _to_redesignation_18_221_html(
            document=(
                "<p>&sect;221. Redesignated to R.S. 18:66 by Acts 2017, "
                "No. 177, &sect;6, eff. June 14, 2017.</p>"
            )
        ),
        _to_redesignation_18_221_html(
            document=(
                "<p>&sect;221. Redesignated to R.S. 18:66 by Acts 2017, "
                "No. 176, &sect;6, eff. June 14, 2017.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _to_redesignation_18_221_html(include_previous=False),
        _to_redesignation_18_221_html(include_next=False),
    ],
)
def test_source_bound_to_redesignation_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81535"
    digest = louisiana_law._EXACT_TO_REDESIGNATION_OFFICIAL_LOCATORS[url][
        "content_sha256"
    ]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    (
        "document_id",
        "from_section",
        "to_section",
        "_content_sha256",
        "_content_cid",
        "_receipt_sha256",
        "_receipt_cid",
        "element_name",
    ),
    louisiana_law._EXACT_TITLE_30_TO_REDESIGNATION_RECORDS,
)
def test_source_bound_classifier_types_exact_title_30_redesignation_family(
    document_id: str,
    from_section: str,
    to_section: str,
    _content_sha256: str,
    _content_cid: str,
    _receipt_sha256: str,
    _receipt_cid: str,
    element_name: str,
) -> None:
    url = f"https://legis.la.gov/legis/Law.aspx?d={document_id}"
    evidence = louisiana_law._EXACT_TO_REDESIGNATION_OFFICIAL_LOCATORS[url]
    html = _title_30_to_redesignation_html(
        document_id=document_id,
        from_section=from_section,
        to_section=to_section,
        element_name=element_name,
    )

    assert terminal_disposition_from_law_html(html) is None
    assert louisiana_law.statute_from_law_html(html, source_url=url) is None
    assert evidence["content_sha256"] == _content_sha256
    assert evidence["content_cid"] == _content_cid
    assert evidence["receipt_sha256"] == _receipt_sha256
    assert evidence["receipt_cid"] == _receipt_cid
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=_content_sha256,
        )
        == "redesignated_to"
    )


def test_source_bound_title_30_redesignation_rejects_dom_or_text_drift() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=87487"
    evidence = louisiana_law._EXACT_TO_REDESIGNATION_OFFICIAL_LOCATORS[url]
    drifted = _title_30_to_redesignation_html(
        document_id="87487",
        from_section="2501",
        to_section="200",
        element_name="div",
        document=(
            '<p style="text-align:left; text-indent: -0.5in; '
            'margin-left: 0.5in">&sect;2501. Redesignated to R.S. 17:200 '
            "by Acts 2020, No. 317.</p>"
        ),
    )

    assert (
        source_bound_terminal_disposition_from_law_html(
            drifted,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        is None
    )


def test_source_bound_classifier_types_exact_effective_date_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506659"
    evidence = (
        louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    )
    html = _effective_date_redesignation_22_2_1_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_effective_date"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=506659",
            "52647a9b0b01de722ee3aa6b44292509a8dc52e5fdf2ca2a654c5fc64faf0129",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=506659",
            "52647a9b0b01de722ee3aa6b44292509a8dc52e5fdf2ca2a654c5fc64faf0129",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=506659&copy=1",
            "52647a9b0b01de722ee3aa6b44292509a8dc52e5fdf2ca2a654c5fc64faf0129",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=506659", "0" * 64),
    ],
)
def test_source_bound_effective_date_redesignation_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _effective_date_redesignation_22_2_1_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _effective_date_redesignation_22_2_1_html(label="RS 22:2.2"),
        _effective_date_redesignation_22_2_1_html(document_id="506660"),
        _effective_date_redesignation_22_2_1_html(
            form_action="./Law.aspx?d=506660"
        ),
        _effective_date_redesignation_22_2_1_html(
            print_href="LawPrint.aspx?d=506660"
        ),
        _effective_date_redesignation_22_2_1_html(
            document=(
                "<p>&sect;2.1. &nbsp;Redesignated as R.S. 22:43 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_2_1_html(
            document=(
                "<p>&sect;2.1. &nbsp;Redesignated as R.S. 22:42 by Acts "
                "2008, No. 416, &sect;1, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_2_1_html(
            document=(
                "<p>&sect;2.1. &nbsp;Redesignated as R.S. 22:42 by Acts "
                "2008, No. 415, &sect;2, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_2_1_html(
            document=(
                "<p>&sect;2.1. &nbsp;Redesignated as R.S. 22:42 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 2, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_2_1_html(
            document=(
                "<p>&sect;2.1. &nbsp;Redesignated as R.S. 22:42 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _effective_date_redesignation_22_2_1_html(include_previous=False),
        _effective_date_redesignation_22_2_1_html(include_next=False),
    ],
)
def test_source_bound_effective_date_redesignation_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506659"
    digest = louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[
        url
    ]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_rs_22_4_effective_date_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506671"
    evidence = (
        louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    )
    html = _effective_date_redesignation_22_4_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_effective_date"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=506671",
            "a9071cb23c221ffbc9d71464408f069829e1b4ce7bd85799ab8af53b2ae519b5",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=506671",
            "a9071cb23c221ffbc9d71464408f069829e1b4ce7bd85799ab8af53b2ae519b5",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=506671&copy=1",
            "a9071cb23c221ffbc9d71464408f069829e1b4ce7bd85799ab8af53b2ae519b5",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=506671", "0" * 64),
    ],
)
def test_source_bound_rs_22_4_effective_date_redesignation_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _effective_date_redesignation_22_4_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _effective_date_redesignation_22_4_html(label="RS 22:5"),
        _effective_date_redesignation_22_4_html(document_id="506672"),
        _effective_date_redesignation_22_4_html(
            form_action="./Law.aspx?d=506672"
        ),
        _effective_date_redesignation_22_4_html(
            print_href="LawPrint.aspx?d=506672"
        ),
        _effective_date_redesignation_22_4_html(
            document=(
                "<p>&sect;4. &nbsp;Redesignated as R.S. 22:13 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_4_html(
            document=(
                "<p>&sect;4. &nbsp;Redesignated as R.S. 22:12 by Acts "
                "2008, No. 416, &sect;1, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_4_html(
            document=(
                "<p>&sect;4. &nbsp;Redesignated as R.S. 22:12 by Acts "
                "2008, No. 415, &sect;2, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_4_html(
            document=(
                "<p>&sect;4. &nbsp;Redesignated as R.S. 22:12 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 2, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_4_html(
            document=(
                "<p>&sect;4. &nbsp;Redesignated as R.S. 22:12 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _effective_date_redesignation_22_4_html(include_previous=False),
        _effective_date_redesignation_22_4_html(include_next=False),
    ],
)
def test_source_bound_rs_22_4_effective_date_redesignation_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506671"
    digest = louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[
        url
    ]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_rs_22_5_effective_date_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506672"
    evidence = (
        louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    )
    html = _effective_date_redesignation_22_5_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_effective_date"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=506672",
            "cd7a3e48ab2167fc9f9e6d19f6141973ad92b526c7f7ae6c93c5d7ed2892e6c5",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=506672",
            "cd7a3e48ab2167fc9f9e6d19f6141973ad92b526c7f7ae6c93c5d7ed2892e6c5",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=506672&copy=1",
            "cd7a3e48ab2167fc9f9e6d19f6141973ad92b526c7f7ae6c93c5d7ed2892e6c5",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=506672", "0" * 64),
    ],
)
def test_source_bound_rs_22_5_effective_date_redesignation_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _effective_date_redesignation_22_5_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _effective_date_redesignation_22_5_html(label="RS 22:6"),
        _effective_date_redesignation_22_5_html(document_id="506673"),
        _effective_date_redesignation_22_5_html(
            form_action="./Law.aspx?d=506673"
        ),
        _effective_date_redesignation_22_5_html(
            print_href="LawPrint.aspx?d=506673"
        ),
        _effective_date_redesignation_22_5_html(
            document=(
                "<p>&sect;5. &nbsp;Redesignated as R.S. 22:47 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_5_html(
            document=(
                "<p>&sect;5. &nbsp;Redesignated as R.S. 22:46 by Acts "
                "2008, No. 416, &sect;1, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_5_html(
            document=(
                "<p>&sect;5. &nbsp;Redesignated as R.S. 22:46 by Acts "
                "2008, No. 415, &sect;2, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_5_html(
            document=(
                "<p>&sect;5. &nbsp;Redesignated as R.S. 22:46 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 2, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_5_html(
            document=(
                "<p>&sect;5. &nbsp;Redesignated as R.S. 22:46 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _effective_date_redesignation_22_5_html(include_previous=False),
        _effective_date_redesignation_22_5_html(include_next=False),
    ],
)
def test_source_bound_rs_22_5_effective_date_redesignation_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506672"
    digest = louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[
        url
    ]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


def test_source_bound_classifier_types_exact_rs_22_6_effective_date_redesignation() -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506673"
    evidence = (
        louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    )
    html = _effective_date_redesignation_22_6_html()

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == "redesignated_effective_date"
    )


@pytest.mark.parametrize(
    ("source_url", "content_sha256"),
    [
        (
            "http://legis.la.gov/legis/Law.aspx?d=506673",
            "e03c10fd55eb35efd6594e3afe3cdd4414c470e9fff32f794db3e678593e5995",
        ),
        (
            "https://www.legis.la.gov/legis/Law.aspx?d=506673",
            "e03c10fd55eb35efd6594e3afe3cdd4414c470e9fff32f794db3e678593e5995",
        ),
        (
            "https://legis.la.gov/legis/Law.aspx?d=506673&copy=1",
            "e03c10fd55eb35efd6594e3afe3cdd4414c470e9fff32f794db3e678593e5995",
        ),
        ("https://legis.la.gov/legis/Law.aspx?d=506673", "0" * 64),
    ],
)
def test_source_bound_rs_22_6_effective_date_redesignation_rejects_url_or_digest_drift(
    source_url: str,
    content_sha256: str,
) -> None:
    assert (
        source_bound_terminal_disposition_from_law_html(
            _effective_date_redesignation_22_6_html(),
            source_url=source_url,
            content_sha256=content_sha256,
        )
        is None
    )


@pytest.mark.parametrize(
    "html",
    [
        _effective_date_redesignation_22_6_html(label="RS 22:7"),
        _effective_date_redesignation_22_6_html(document_id="506674"),
        _effective_date_redesignation_22_6_html(
            form_action="./Law.aspx?d=506674"
        ),
        _effective_date_redesignation_22_6_html(
            print_href="LawPrint.aspx?d=506674"
        ),
        _effective_date_redesignation_22_6_html(
            document=(
                "<p>&sect;6. &nbsp;Redesignated as R.S. 22:48 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_6_html(
            document=(
                "<p>&sect;6. &nbsp;Redesignated as R.S. 22:47 by Acts "
                "2008, No. 416, &sect;1, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_6_html(
            document=(
                "<p>&sect;6. &nbsp;Redesignated as R.S. 22:47 by Acts "
                "2008, No. 415, &sect;2, eff. Jan. 1, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_6_html(
            document=(
                "<p>&sect;6. &nbsp;Redesignated as R.S. 22:47 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 2, 2009.</p>"
            )
        ),
        _effective_date_redesignation_22_6_html(
            document=(
                "<p>&sect;6. &nbsp;Redesignated as R.S. 22:47 by Acts "
                "2008, No. 415, &sect;1, eff. Jan. 1, 2009.</p>"
                "<p>This enacted paragraph prevents exclusion.</p>"
            )
        ),
        _effective_date_redesignation_22_6_html(include_previous=False),
        _effective_date_redesignation_22_6_html(include_next=False),
    ],
)
def test_source_bound_rs_22_6_effective_date_redesignation_rejects_structure_or_text_drift(
    html: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506673"
    digest = louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[
        url
    ]["content_sha256"]
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )


@pytest.mark.parametrize(
    ("url", "label", "document_id", "heading", "disposition"),
    _TITLE_22_RENUMBERING_CASES,
)
def test_source_bound_classifier_types_exact_title_22_renumbering_set(
    url: str,
    label: str,
    document_id: str,
    heading: str,
    disposition: str,
) -> None:
    evidence = louisiana_law._EXACT_TITLE_22_RENUMBERING_OFFICIAL_LOCATORS[url]
    html = _title_22_renumbering_html(
        label=label,
        document_id=document_id,
        heading=heading,
    )

    assert terminal_disposition_from_law_html(html) is None
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256=evidence["content_sha256"],
        )
        == disposition
    )


@pytest.mark.parametrize(
    ("url", "label", "document_id", "heading", "_disposition"),
    _TITLE_22_RENUMBERING_CASES,
)
def test_source_bound_title_22_renumbering_set_rejects_url_or_digest_drift(
    url: str,
    label: str,
    document_id: str,
    heading: str,
    _disposition: str,
) -> None:
    evidence = louisiana_law._EXACT_TITLE_22_RENUMBERING_OFFICIAL_LOCATORS[url]
    html = _title_22_renumbering_html(
        label=label,
        document_id=document_id,
        heading=heading,
    )
    drifted_urls = [
        url.replace("https://", "http://", 1),
        url.replace("legis.la.gov", "www.legis.la.gov", 1),
        f"{url}&copy=1",
    ]

    for drifted_url in drifted_urls:
        assert (
            source_bound_terminal_disposition_from_law_html(
                html,
                source_url=drifted_url,
                content_sha256=evidence["content_sha256"],
            )
            is None
        )
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256="0" * 64,
        )
        is None
    )


@pytest.mark.parametrize(
    ("url", "label", "document_id", "heading", "_disposition"),
    _TITLE_22_RENUMBERING_CASES,
)
def test_source_bound_title_22_renumbering_set_rejects_structure_or_text_drift(
    url: str,
    label: str,
    document_id: str,
    heading: str,
    _disposition: str,
) -> None:
    evidence = louisiana_law._EXACT_TITLE_22_RENUMBERING_OFFICIAL_LOCATORS[url]
    digest = evidence["content_sha256"]
    section = label.split(":", 1)[1]
    exact_document = f"<p>&sect;{section}. &nbsp;{heading}</p>"
    variants = [
        _title_22_renumbering_html(
            label=label.replace("RS 22:", "RS 21:", 1),
            document_id=document_id,
            heading=heading,
        ),
        _title_22_renumbering_html(
            label=label,
            document_id=f"{document_id}0",
            heading=heading,
        ),
        _title_22_renumbering_html(
            label=label,
            document_id=document_id,
            heading=heading,
            form_action=f"./Law.aspx?d={document_id}&copy=1",
        ),
        _title_22_renumbering_html(
            label=label,
            document_id=document_id,
            heading=heading,
            print_href=f"LawPrint.aspx?d={document_id}&copy=1",
        ),
        _title_22_renumbering_html(
            label=label,
            document_id=document_id,
            heading=heading,
            document=f"<p>&sect;{section}A. &nbsp;{heading}</p>",
        ),
        _title_22_renumbering_html(
            label=label,
            document_id=document_id,
            heading=heading,
            document=exact_document.replace("R.S. 22:", "R.S. 23:", 1),
        ),
        _title_22_renumbering_html(
            label=label,
            document_id=document_id,
            heading=heading,
            document=exact_document.replace("No. 415", "No. 416"),
        ),
        _title_22_renumbering_html(
            label=label,
            document_id=document_id,
            heading=heading,
            document=exact_document.replace("Jan. 1, 2009", "Jan. 2, 2009"),
        ),
        _title_22_renumbering_html(
            label=label,
            document_id=document_id,
            heading=heading,
            document=(
                f"{exact_document}<p>This enacted paragraph prevents exclusion.</p>"
            ),
        ),
        _title_22_renumbering_html(
            label=label,
            document_id=document_id,
            heading=heading,
            include_previous=False,
        ),
        _title_22_renumbering_html(
            label=label,
            document_id=document_id,
            heading=heading,
            include_next=False,
        ),
    ]

    for html in variants:
        assert (
            source_bound_terminal_disposition_from_law_html(
                html,
                source_url=url,
                content_sha256=digest,
            )
            is None
        )


def _projected_title_22_renumbering_html(evidence: dict[str, str]) -> str:
    return _title_22_renumbering_html(
        label=evidence["label"],
        document_id=evidence["document_id"],
        heading=evidence["heading"],
        document=f'<p>{evidence["document_text"]}</p>',
    )


def test_source_bound_projected_title_22_set_is_exact_and_complete() -> None:
    evidence_by_url = (
        louisiana_law._EXACT_TITLE_22_PROJECTED_RENUMBERING_OFFICIAL_LOCATORS
    )
    common_rows = (
        louisiana_law._EXACT_TITLE_22_PROJECTED_COMMON_RENUMBERING_ROWS.strip()
        + "\n"
    )

    assert len(common_rows.splitlines()) == 747
    assert hashlib.sha256(common_rows.encode()).hexdigest() == (
        "77f9b2759bb273dc52376cc6b455e7e1f070aefa019bd1c0cda87a7962419feb"
    )
    assert len(evidence_by_url) == 751
    assert not (
        set(evidence_by_url)
        & set(louisiana_law._EXACT_TITLE_22_RENUMBERING_OFFICIAL_LOCATORS)
    )
    assert len({item["content_sha256"] for item in evidence_by_url.values()}) == 751
    assert sum(
        item["disposition"] == "redesignated_effective_date"
        for item in evidence_by_url.values()
    ) == 750
    assert sum(
        item["disposition"] == "split_redesignation_effective_date"
        for item in evidence_by_url.values()
    ) == 1

    for url, evidence in evidence_by_url.items():
        document_id = url.rsplit("=", 1)[1]
        assert url == f"https://legis.la.gov/legis/Law.aspx?d={document_id}"
        assert evidence["document_id"] == document_id
        assert evidence["form_action"] == f"./Law.aspx?d={document_id}"
        assert evidence["print_href"] == f"LawPrint.aspx?d={document_id}"
        assert evidence["label"].startswith("RS 22:")
        assert len(evidence["content_sha256"]) == 64
        assert set(evidence["content_sha256"]) <= set("0123456789abcdef")

        html = _projected_title_22_renumbering_html(evidence)
        assert terminal_disposition_from_law_html(html) is None
        assert (
            source_bound_terminal_disposition_from_law_html(
                html,
                source_url=url,
                content_sha256=evidence["content_sha256"],
            )
            == evidence["disposition"]
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://legis.la.gov/legis/Law.aspx?d=506700",
        "https://legis.la.gov/legis/Law.aspx?d=506908",
        "https://legis.la.gov/legis/Law.aspx?d=507793",
        "https://legis.la.gov/legis/Law.aspx?d=508471",
        "https://legis.la.gov/legis/Law.aspx?d=508480",
    ],
)
def test_source_bound_projected_title_22_set_rejects_url_or_digest_drift(
    url: str,
) -> None:
    evidence = (
        louisiana_law._EXACT_TITLE_22_PROJECTED_RENUMBERING_OFFICIAL_LOCATORS[
            url
        ]
    )
    html = _projected_title_22_renumbering_html(evidence)

    for drifted_url in (
        url.replace("https://", "http://", 1),
        url.replace("legis.la.gov", "www.legis.la.gov", 1),
        f"{url}&copy=1",
    ):
        assert (
            source_bound_terminal_disposition_from_law_html(
                html,
                source_url=drifted_url,
                content_sha256=evidence["content_sha256"],
            )
            is None
        )
    assert (
        source_bound_terminal_disposition_from_law_html(
            html,
            source_url=url,
            content_sha256="0" * 64,
        )
        is None
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://legis.la.gov/legis/Law.aspx?d=506700",
        "https://legis.la.gov/legis/Law.aspx?d=508480",
    ],
)
def test_source_bound_projected_title_22_set_rejects_identity_or_text_drift(
    url: str,
) -> None:
    evidence = (
        louisiana_law._EXACT_TITLE_22_PROJECTED_RENUMBERING_OFFICIAL_LOCATORS[
            url
        ]
    )
    digest = evidence["content_sha256"]
    exact_document = f'<p>{evidence["document_text"]}</p>'
    changed_document = exact_document.replace("No. ", "No. 9", 1)
    variants = [
        _title_22_renumbering_html(
            label=evidence["label"].replace("RS 22:", "RS 21:", 1),
            document_id=evidence["document_id"],
            heading=evidence["heading"],
            document=exact_document,
        ),
        _title_22_renumbering_html(
            label=evidence["label"],
            document_id=f'{evidence["document_id"]}0',
            heading=evidence["heading"],
            form_action=evidence["form_action"],
            print_href=evidence["print_href"],
            document=exact_document,
        ),
        _title_22_renumbering_html(
            label=evidence["label"],
            document_id=evidence["document_id"],
            heading=evidence["heading"],
            form_action=f'{evidence["form_action"]}&copy=1',
            document=exact_document,
        ),
        _title_22_renumbering_html(
            label=evidence["label"],
            document_id=evidence["document_id"],
            heading=evidence["heading"],
            print_href=f'{evidence["print_href"]}&copy=1',
            document=exact_document,
        ),
        _title_22_renumbering_html(
            label=evidence["label"],
            document_id=evidence["document_id"],
            heading=evidence["heading"],
            document=changed_document,
        ),
        _title_22_renumbering_html(
            label=evidence["label"],
            document_id=evidence["document_id"],
            heading=evidence["heading"],
            document=f"{exact_document}<p>Operative text must prevent exclusion.</p>",
        ),
        _title_22_renumbering_html(
            label=evidence["label"],
            document_id=evidence["document_id"],
            heading=evidence["heading"],
            document=exact_document,
            include_previous=False,
        ),
        _title_22_renumbering_html(
            label=evidence["label"],
            document_id=evidence["document_id"],
            heading=evidence["heading"],
            document=exact_document,
            include_next=False,
        ),
    ]

    for html in variants:
        assert (
            source_bound_terminal_disposition_from_law_html(
                html,
                source_url=url,
                content_sha256=digest,
            )
            is None
        )


@pytest.mark.anyio
async def test_strict_frontier_closes_retained_projected_title_22_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = os.getenv("STATE_LAWS_TEST_LA_EVIDENCE_ROOT", "").strip()
    if not evidence_root:
        pytest.skip("requires retained Louisiana acquisition evidence")

    evidence_by_url = (
        louisiana_law._EXACT_TITLE_22_PROJECTED_RENUMBERING_OFFICIAL_LOCATORS
    )
    urls = list(evidence_by_url)
    objects_dir = Path(evidence_root) / "LA" / "objects"
    payload_by_url: dict[str, bytes] = {}
    for url, evidence in evidence_by_url.items():
        payload = (objects_dir / f'{evidence["content_sha256"]}.bin').read_bytes()
        assert hashlib.sha256(payload).hexdigest() == evidence["content_sha256"]
        html = payload.decode("utf-8", errors="replace")
        assert terminal_disposition_from_law_html(html) is None
        payload_by_url[url] = payload

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), payload_by_url)

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=urls,
        max_statutes=None,
    )

    assert rows == []
    frontier = scraper._last_louisiana_full_frontier
    assert frontier["closed"] is True
    assert frontier["law_pages_discovered"] == 751
    assert frontier["law_pages_requested"] == 751
    assert frontier["law_pages_fetched"] == 751
    assert frontier["law_pages_classified"] == 751
    assert frontier["terminal_pages_excluded"] == 751
    assert frontier["terminal_disposition_counts"] == {
        "redesignated_effective_date": 750,
        "split_redesignation_effective_date": 1,
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_act_section_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=78416"
    payload = _act_section_suffix_redesignation_html().encode()
    evidence = louisiana_law._EXACT_ACT_SECTION_SUFFIX_REDESIGNATIONS[url]
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_act_section_suffix": 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_chapter_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=89224"
    payload = _chapter_wrapped_redesignation_html().encode()
    evidence = (
        louisiana_law._EXACT_CHAPTER_WRAPPED_REDESIGNATION_OFFICIAL_LOCATORS[url]
    )
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_chapter_wrapper": 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_range_redesignation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81194"
    payload = _range_redesignation_html().encode()
    evidence = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_range": 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_fourth_range_redesignation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81494"
    payload = _range_redesignation_18_1651_html().encode()
    evidence = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_range": 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_title_29_range_redesignation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=85614"
    payload = _range_redesignation_29_461_html().encode()
    evidence = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_range": 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_title_30_range_redesignation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=86914"
    payload = _range_redesignation_30_1051_html().encode()
    evidence = louisiana_law._EXACT_RANGE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_range": 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_to_redesignation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=81535"
    payload = _to_redesignation_18_221_html().encode()
    evidence = louisiana_law._EXACT_TO_REDESIGNATION_OFFICIAL_LOCATORS[url]
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_to": 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_effective_date_redesignation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506659"
    payload = _effective_date_redesignation_22_2_1_html().encode()
    evidence = (
        louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    )
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_effective_date": 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_rs_22_4_effective_date_redesignation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506671"
    payload = _effective_date_redesignation_22_4_html().encode()
    evidence = (
        louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    )
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_effective_date": 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_rs_22_5_effective_date_redesignation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506672"
    payload = _effective_date_redesignation_22_5_html().encode()
    evidence = (
        louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    )
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_effective_date": 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_for_rs_22_6_effective_date_redesignation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=506673"
    payload = _effective_date_redesignation_22_6_html().encode()
    evidence = (
        louisiana_law._EXACT_EFFECTIVE_DATE_REDESIGNATION_OFFICIAL_LOCATORS[url]
    )
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "redesignated_effective_date": 1
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("url", "label", "document_id", "heading", "disposition"),
    _TITLE_22_RENUMBERING_CASES,
)
async def test_strict_frontier_passes_computed_digest_for_title_22_renumbering_set(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    label: str,
    document_id: str,
    heading: str,
    disposition: str,
) -> None:
    payload = _title_22_renumbering_html(
        label=label,
        document_id=document_id,
        heading=heading,
    ).encode()
    evidence = louisiana_law._EXACT_TITLE_22_RENUMBERING_OFFICIAL_LOCATORS[url]
    monkeypatch.setitem(
        evidence,
        "content_sha256",
        hashlib.sha256(payload).hexdigest(),
    )

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        disposition: 1
    }


@pytest.mark.anyio
async def test_strict_frontier_passes_computed_digest_to_source_bound_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=763423"
    payload = _empty_official_locator_html().encode()
    evidence = louisiana_law._EXACT_EMPTY_OFFICIAL_LOCATORS[url]
    monkeypatch.setitem(evidence, "content_sha256", hashlib.sha256(payload).hexdigest())

    async def _frontier(_self, requested, **_kwargs):
        return _batch_result(list(requested), {url: payload})

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        LouisianaScraper,
        "_fetch_page_contents_with_archival_fallback",
        _frontier,
    )
    monkeypatch.setattr(
        LouisianaScraper,
        "_write_partial_checkpoint",
        lambda *_args, **_kwargs: True,
    )

    scraper = LouisianaScraper("LA", "Louisiana")
    rows = await scraper._scrape_law_page_urls(
        code_name="Louisiana Revised Statutes",
        law_urls=[url],
        max_statutes=None,
    )

    assert rows == []
    assert scraper._last_louisiana_full_frontier["closed"] is True
    assert scraper._last_louisiana_full_frontier["law_pages_classified"] == 1
    assert scraper._last_louisiana_full_frontier["terminal_disposition_counts"] == {
        "empty_official_locator": 1
    }


def test_terminal_classifier_does_not_exclude_partially_repealed_active_law() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 3:3801</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;3801. Horticulture Commission</p>
      <p>A. The Horticulture Commission is created.</p>
      <p>B.(1) A current member serves. (2) Repealed by Acts 2024, No. 643.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_does_not_exclude_blank_marker_with_enacted_body() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:51</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>CODE PRELIMINARY TITLE [BLANK]</p>
      <p>&sect;51. Civil rights and duties</p>
      <p>Women have the same rights, authority, privileges, and immunities as men.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_types_exact_unbracketed_blank_heading() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:1122.102</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;1122.102. Blank</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) == "blank"


def test_terminal_classifier_does_not_exclude_unbracketed_blank_with_body() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:1122.102</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;1122.102. Blank</p>
      <p>This text makes the section substantive rather than a terminal marker.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_types_exact_bracketed_reserved_heading() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 10:1-105</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;1-105. [Reserved.]</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) == "reserved"


@pytest.mark.parametrize(
    "heading",
    ["Reserved.", "[Reserved for future use.]", "[Reservation proposed.]"],
)
def test_terminal_classifier_rejects_reserved_heading_shape_drift(
    heading: str,
) -> None:
    html = f"""
    <span id="ctl00_PageBody_LabelName">RS 10:1-105</span>
    <span id="ctl00_PageBody_LabelDocument"><p>&sect;1-105. {heading}</p></span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_does_not_exclude_reserved_heading_with_body() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 10:1-105</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;1-105. [Reserved.]</p>
      <p>This enacted paragraph prevents terminal classification.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_types_exact_bracketed_see_cross_reference() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:2354</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;2354. [See R.S. 9:2372 and 2373, Acts 1995, No. 402, &sect;1]</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) == "cross_reference"


@pytest.mark.parametrize(
    "heading",
    [
        "See R.S. 9:2372 and 2373, Acts 1995, No. 402, §1",
        "[See R.S. 9:2372 and 2373]",
        "[See another source]",
    ],
)
def test_terminal_classifier_rejects_cross_reference_shape_drift(
    heading: str,
) -> None:
    html = f"""
    <span id="ctl00_PageBody_LabelName">RS 9:2354</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;2354. {heading}</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_does_not_exclude_cross_reference_with_body() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:2354</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;2354. [See R.S. 9:2372 and 2373, Acts 1995, No. 402, &sect;1]</p>
      <p>This enacted paragraph prevents terminal classification.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_types_exact_blank_civil_code_cross_reference() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:2949</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;2949. [Blank - See C.C. Art. 477(B)]</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) == "blank_cross_reference"


@pytest.mark.parametrize(
    ("label", "heading"),
    [
        ("CC 2949", "[Blank - See C.C. Art. 477(B)]"),
        ("RS 9:2949", "Blank - See C.C. Art. 477(B)"),
        ("RS 9:2949", "[Blank - See C.C. Art. 477(B) and related law]"),
        ("RS 9:2949", "[Blank - See another source]"),
    ],
)
def test_terminal_classifier_rejects_blank_cross_reference_shape_drift(
    label: str,
    heading: str,
) -> None:
    html = f"""
    <span id="ctl00_PageBody_LabelName">{label}</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;2949. {heading}</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_does_not_exclude_blank_cross_reference_with_body() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:2949</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;2949. [Blank - See C.C. Art. 477(B)]</p>
      <p>This enacted paragraph prevents terminal classification.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_types_exact_act_termination() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:3391</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>CHAPTER 5. REMOVAL AND PRESERVATION OF PROPERTY</p>
      <p>DURING EMERGENCIES AND DISASTERS</p>
      <p>&sect;3391. Terminated by Acts 2005, 1<sup>st</sup> Ex. Sess.,
      No. 56, eff. June 30, 2006.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) == "terminated"


@pytest.mark.parametrize(
    "heading",
    [
        "Terminated.",
        "Terminated by Acts 2005, No. 56.",
        "Terminated by another authority, eff. June 30, 2006.",
        "Termination proposed by Acts 2005, No. 56, eff. June 30, 2006.",
    ],
)
def test_terminal_classifier_rejects_act_termination_shape_drift(
    heading: str,
) -> None:
    html = f"""
    <span id="ctl00_PageBody_LabelName">RS 9:3391</span>
    <span id="ctl00_PageBody_LabelDocument"><p>&sect;3391. {heading}</p></span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_does_not_exclude_act_termination_with_body() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:3391</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;3391. Terminated by Acts 2005, 1st Ex. Sess., No. 56,
      eff. June 30, 2006.</p>
      <p>This enacted paragraph prevents terminal classification.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


@pytest.mark.parametrize(
    ("label", "section", "target"),
    [
        ("RS 9:4814", "4814", "9:4856"),
        ("RS 9:4815", "4815", "9:4857"),
    ],
)
def test_terminal_classifier_types_exact_redesignation_by_act(
    label: str,
    section: str,
    target: str,
) -> None:
    html = f"""
    <span id="ctl00_PageBody_LabelName">{label}</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;{section}. Redesignated as R.S. {target} pursuant to
      Acts 2019, No. 325.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) == "redesignated"


def test_terminal_classifier_types_exact_redesignation_by_act_section() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 13:621.42.1</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;621.42.1. Redesignated as R.S. 13:1141 by Acts 2012,
      No. 474, &sect;6.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) == "redesignated"


def test_terminal_classifier_types_exact_pursuant_redesignation_with_act_section() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 33:1422</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;1422. Redesignated as R.S. 13:5522 pursuant to Acts 2011,
      No. 248, &sect;3.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) == "redesignated"


@pytest.mark.parametrize(
    ("label", "heading"),
    [
        (
            "RS 13:621.42.1",
            "Redesignated as R.S. 13:621.42.1 by Acts 2012, No. 474, §6.",
        ),
        (
            "CC 621.42.1",
            "Redesignated as R.S. 13:1141 by Acts 2012, No. 474, §6.",
        ),
        (
            "RS 13:621.42.1",
            "Redesignated as R.S. 13:1141 by Acts 2012, No. 474.",
        ),
        (
            "RS 13:621.42.1",
            "Redesignated as R.S. 13:1141 under Acts 2012, No. 474, §6.",
        ),
    ],
)
def test_terminal_classifier_rejects_redesignation_by_act_section_drift(
    label: str,
    heading: str,
) -> None:
    html = f"""
    <span id="ctl00_PageBody_LabelName">{label}</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;621.42.1. {heading}</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_does_not_exclude_act_section_redesignation_with_body() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 13:621.42.1</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;621.42.1. Redesignated as R.S. 13:1141 by Acts 2012,
      No. 474, &sect;6.</p>
      <p>This enacted paragraph prevents terminal classification.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


@pytest.mark.parametrize(
    ("label", "heading"),
    [
        (
            "RS 9:4814",
            "Redesignated as R.S. 9:4814 pursuant to Acts 2019, No. 325.",
        ),
        ("CC 4814", "Redesignated as R.S. 9:4856 pursuant to Acts 2019, No. 325."),
        ("RS 9:4814", "Redesignated as R.S. 9:4856."),
        ("RS 9:4814", "Proposed redesignation as R.S. 9:4856 by Act 325."),
    ],
)
def test_terminal_classifier_rejects_redesignation_by_act_shape_drift(
    label: str,
    heading: str,
) -> None:
    html = f"""
    <span id="ctl00_PageBody_LabelName">{label}</span>
    <span id="ctl00_PageBody_LabelDocument"><p>&sect;4814. {heading}</p></span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_does_not_exclude_redesignation_by_act_with_body() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:4814</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;4814. Redesignated as R.S. 9:4856 pursuant to Acts 2019,
      No. 325, &sect;3.</p>
      <p>This enacted paragraph prevents terminal classification.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_types_exact_blank_redesignation() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:2788</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>CHAPTER 5. INTEREST UPON ACCRUED</p>
      <p>INTEREST; EXCEPTIONS</p>
      <p>&sect;2788. [Blank] Acts 1986, No. 584, &sect;3, redesignated
      R.S. 9:2788 as R.S. 9:3509.2.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) == "redesignated"


@pytest.mark.parametrize(
    ("label", "heading"),
    [
        (
            "RS 9:2787",
            "[Blank] Acts 1986, No. 584, §3, redesignated "
            "R.S. 9:2788 as R.S. 9:3509.2.",
        ),
        (
            "RS 9:2788",
            "[Blank] Acts 1986, No. 584, §3, redesignated "
            "R.S. 9:2788 as R.S. 9:2788.",
        ),
        (
            "RS 9:2788",
            "Acts 1986, No. 584, §3, redesignated "
            "R.S. 9:2788 as R.S. 9:3509.2.",
        ),
    ],
)
def test_terminal_classifier_rejects_redesignation_identity_drift(
    label: str,
    heading: str,
) -> None:
    html = f"""
    <span id="ctl00_PageBody_LabelName">{label}</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;2788. {heading}</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def test_terminal_classifier_does_not_exclude_redesignation_with_body() -> None:
    html = """
    <span id="ctl00_PageBody_LabelName">RS 9:2788</span>
    <span id="ctl00_PageBody_LabelDocument">
      <p>&sect;2788. [Blank] Acts 1986, No. 584, &sect;3, redesignated
      R.S. 9:2788 as R.S. 9:3509.2.</p>
      <p>This enacted paragraph prevents terminal classification.</p>
    </span>
    """

    assert terminal_disposition_from_law_html(html) is None


def _bind_operative_dot_label_fixture_digest(
    monkeypatch: pytest.MonkeyPatch,
    html: str,
) -> str:
    url = "https://legis.la.gov/legis/Law.aspx?d=1238853"
    evidence = dict(louisiana_law._EXACT_OPERATIVE_LABEL_CORRECTIONS[url])
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    evidence["content_sha256"] = digest
    monkeypatch.setitem(
        louisiana_law._EXACT_OPERATIVE_LABEL_CORRECTIONS,
        url,
        evidence,
    )
    return digest


def test_source_bound_operative_dot_label_normalizes_exact_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=1238853"
    html = _operative_dot_label_html()

    assert louisiana_law.parse_label("RS 32.1270.41") is None
    assert louisiana_law.statute_from_law_html(html, source_url=url) is None

    digest = _bind_operative_dot_label_fixture_digest(monkeypatch, html)
    assert (
        louisiana_law.source_bound_operative_label_correction_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        == "RS 32:1270.41"
    )
    row = louisiana_law.statute_from_law_html(
        html,
        source_url=url,
        content_sha256=digest,
    )

    assert row is not None
    assert row.title_number == "32"
    assert row.section_number == "1270.41"
    assert row.section_name == "Exclusiveness"
    assert row.statute_id == "Louisiana Revised Statutes § RS 32:1270.41"
    assert row.official_cite == "La. RS 32:1270.41"
    assert row.source_url == url
    assert row.full_text == (
        "This Part provides exclusive remedies, warranties, and peremptive "
        "periods as between the manufacturer, dealer, and consumer, relative "
        "to nonconformity defects as defined in this Part, and no other "
        "provisions of law relative to recreational vehicle warranties and "
        "redhibitory vices and defects shall apply. Nothing herein shall be "
        "construed to affect or limit any warranty of title. Acts 2021, No. "
        "220, §1."
    )
    assert row.structured_data["source_label"] == "RS 32.1270.41"
    assert row.structured_data["normalized_label"] == "RS 32:1270.41"
    assert row.structured_data["source_bound_label_correction"] == (
        "exact_official_louisiana_rs_separator_typo"
    )


def test_source_bound_operative_dot_label_rejects_url_or_digest_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=1238853"
    html = _operative_dot_label_html()
    digest = _bind_operative_dot_label_fixture_digest(monkeypatch, html)

    assert (
        louisiana_law.source_bound_operative_label_correction_from_law_html(
            html,
            source_url="https://legis.la.gov/legis/Law.aspx?d=1238854",
            content_sha256=digest,
        )
        is None
    )
    assert (
        louisiana_law.source_bound_operative_label_correction_from_law_html(
            html,
            source_url=url,
            content_sha256="0" * 64,
        )
        is None
    )


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("RS 32.1270.41", "RS 32.1270.42"),
        ("./Law.aspx?d=1238853", "./Law.aspx?d=1238854"),
        ('value="1238853"', 'value="1238854"'),
        ("LawPrint.aspx?d=1238853", "LawPrint.aspx?d=1238854"),
        ("ctl00_PageBody_ButtonPrevious", "wrong-previous-button"),
        ('id="WPMainDoc"', 'id="wrong-document-wrapper"'),
        ("Acts 2021, No. 220", "Acts 2021, No. 221"),
    ],
)
def test_source_bound_operative_dot_label_rejects_dom_or_text_drift(
    monkeypatch: pytest.MonkeyPatch,
    original: str,
    replacement: str,
) -> None:
    url = "https://legis.la.gov/legis/Law.aspx?d=1238853"
    html = _operative_dot_label_html().replace(original, replacement, 1)
    digest = _bind_operative_dot_label_fixture_digest(monkeypatch, html)

    assert (
        louisiana_law.source_bound_operative_label_correction_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )
    assert (
        louisiana_law.statute_from_law_html(
            html,
            source_url=url,
            content_sha256=digest,
        )
        is None
    )
